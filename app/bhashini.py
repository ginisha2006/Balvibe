from __future__ import annotations

import re
from typing import Any

import requests

from .config import Settings

PAUSE_RE = re.compile(r"\[PAUSE(?:\s+(\d+(?:\.\d+)?)\s*(?:seconds?|s)?)?\]", re.IGNORECASE)
DEFAULT_TIMEOUT_SECONDS = 30


class BhashiniError(RuntimeError):
    """Normalized BHASHINI/ULCA error that is safe to surface through the API."""


def _language_code(locale: str) -> str:
    value = (locale or "").strip()
    if not value:
        raise ValueError("A target language is required.")
    # BalVibe uses BCP-47-like locales (hi-IN); BHASHINI uses ISO-639 codes (hi).
    return value.split("-", 1)[0].lower()


def _split_text(text: str, max_len: int = 1800) -> list[str]:
    chunks: list[str] = []
    remaining = text.strip()
    while len(remaining) > max_len:
        cut = remaining.rfind(".", 0, max_len)
        if cut < int(max_len * 0.55):
            cut = remaining.rfind(" ", 0, max_len)
        if cut < 1:
            cut = max_len
        include = 1 if cut < len(remaining) and remaining[cut:cut + 1] == "." else 0
        chunks.append(remaining[:cut + include].strip())
        remaining = remaining[cut + include:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _safe_json(response: requests.Response, label: str) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise BhashiniError(
            f"BHASHINI {label} returned a non-JSON response (HTTP {response.status_code})."
        ) from exc
    if not isinstance(body, dict):
        raise BhashiniError(f"BHASHINI {label} returned an unexpected response shape.")
    return body


def _raise_http(response: requests.Response, body: dict[str, Any], label: str) -> None:
    if response.ok:
        return
    if response.status_code in {401, 403}:
        raise BhashiniError(
            f"BHASHINI authentication failed during the {label}. "
            "Check BHASHINI_USER_ID and BHASHINI_API_KEY."
        )
    if response.status_code == 429:
        raise BhashiniError(f"BHASHINI rate limit reached during the {label}. Please retry shortly.")
    if response.status_code >= 500:
        raise BhashiniError(f"BHASHINI server error during the {label} (HTTP {response.status_code}).")
    message = body.get("message") or body.get("error") or body.get("detail")
    raise BhashiniError(str(message or f"BHASHINI {label} failed (HTTP {response.status_code})."))


def _pipeline_config(source_language: str, target_language: str, settings: Settings) -> tuple[str, str, str, str]:
    if not settings.bhashini_user_id or not settings.bhashini_api_key:
        raise BhashiniError(
            "BHASHINI credentials are missing. Set BHASHINI_USER_ID and BHASHINI_API_KEY."
        )

    payload = {
        "pipelineTasks": [
            {
                "taskType": "translation",
                "config": {
                    "language": {
                        "sourceLanguage": source_language,
                        "targetLanguage": target_language,
                    }
                },
            }
        ],
        "pipelineRequestConfig": {"pipelineId": settings.bhashini_pipeline_id},
    }

    try:
        response = requests.post(
            settings.bhashini_ulca_config_endpoint,
            headers={
                "Content-Type": "application/json",
                "userID": settings.bhashini_user_id,
                "ulcaApiKey": settings.bhashini_api_key,
            },
            json=payload,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        raise BhashiniError("BHASHINI pipeline config request timed out.") from exc
    except requests.RequestException as exc:
        raise BhashiniError("Could not reach the BHASHINI pipeline config service.") from exc

    body = _safe_json(response, "pipeline config call")
    _raise_http(response, body, "pipeline config call")

    translation_task = next(
        (
            task for task in body.get("pipelineResponseConfig", [])
            if isinstance(task, dict) and task.get("taskType") == "translation"
        ),
        None,
    )
    configs = translation_task.get("config", []) if isinstance(translation_task, dict) else []
    service = next(
        (
            item for item in configs
            if isinstance(item, dict)
            and item.get("language", {}).get("sourceLanguage") == source_language
            and item.get("language", {}).get("targetLanguage") == target_language
        ),
        None,
    )
    if service is None and configs:
        service = configs[0]

    service_id = service.get("serviceId") if isinstance(service, dict) else None
    endpoint = body.get("pipelineInferenceAPIEndPoint") or {}
    inference = endpoint.get("inferenceApiKey") or {}
    auth_name = inference.get("name") or "Authorization"
    auth_value = inference.get("value")
    callback_url = endpoint.get("callbackUrl") or settings.bhashini_inference_url

    if not service_id:
        raise BhashiniError(
            f"BHASHINI has no translation service for {source_language} -> {target_language} "
            "on the configured pipeline."
        )
    if not auth_value:
        raise BhashiniError("BHASHINI pipeline config response did not include an inference API key.")
    if not callback_url:
        raise BhashiniError("BHASHINI pipeline config response did not include a compute endpoint.")

    return str(service_id), str(auth_name), str(auth_value), str(callback_url)


def _compute_translation(
    text: str,
    source_language: str,
    target_language: str,
    service_id: str,
    auth_name: str,
    auth_value: str,
    callback_url: str,
) -> str:
    payload = {
        "pipelineTasks": [
            {
                "taskType": "translation",
                "config": {
                    "language": {
                        "sourceLanguage": source_language,
                        "targetLanguage": target_language,
                    },
                    "serviceId": service_id,
                },
            }
        ],
        "inputData": {"input": [{"source": text}]},
    }

    try:
        response = requests.post(
            callback_url,
            headers={
                "Accept": "*/*",
                auth_name: auth_value,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        raise BhashiniError("BHASHINI translation request timed out.") from exc
    except requests.RequestException as exc:
        raise BhashiniError("Could not reach the BHASHINI translation service.") from exc

    body = _safe_json(response, "pipeline compute call")
    _raise_http(response, body, "pipeline compute call")
    try:
        translated = body["pipelineResponse"][0]["output"][0]["target"]
    except (KeyError, IndexError, TypeError) as exc:
        raise BhashiniError(
            "BHASHINI returned success but no translated text in pipelineResponse[0].output[0].target."
        ) from exc
    if not str(translated).strip():
        raise BhashiniError("BHASHINI returned an empty translation.")
    return str(translated)


def _demo_translation(text: str, target_language: str) -> str:
    demo_all = {
        "hi-IN": {"Hello": "नमस्ते", "Welcome": "स्वागत है", "Look at the numbers": "संख्याओं को ध्यान से देखो", "Now tell me what is missing": "अब बताओ कौन-सी संख्या गायब है", "Great, we are finished": "बहुत अच्छा, हमारा खेल पूरा हुआ"},
        "bn-IN": {"Hello": "নমস্কার", "Welcome": "স্বাগতম", "Look at the numbers": "সংখ্যাগুলো দেখুন", "Now tell me what is missing": "এখন বলুন কোনটি অনুপস্থিত", "Great, we are finished": "দারুণ, আমাদের শেষ হয়েছে"},
        "gu-IN": {"Hello": "નમસ્તે", "Welcome": "સ્વાગત છે", "Look at the numbers": "નંબરો જુઓ", "Now tell me what is missing": "હવે કહો શું ખૂટે છે", "Great, we are finished": "સરસ, અમે પૂર્ણ કર્યું"},
        "kn-IN": {"Hello": "ನಮಸ್ಕಾರ", "Welcome": "ಸ್ವಾಗತ", "Look at the numbers": "ಸಂಖ್ಯೆಗಳನ್ನು ನೋಡಿ", "Now tell me what is missing": "ಈಗ ಯಾವುದು ಕಾಣೆಯಾಗಿದೆ ಎಂದು ಹೇಳಿ", "Great, we are finished": "ಅದ್ಭುತ, ನಾವು ಮುಗಿಸಿದ್ದೇವೆ"},
        "ml-IN": {"Hello": "നമസ്കാരം", "Welcome": "സ്വാഗതം", "Look at the numbers": "നമ്പറുകൾ നോക്കുക", "Now tell me what is missing": "ഇപ്പോൾ എന്താണ് നഷ്ടപ്പെട്ടതെന്ന് പറയുക", "Great, we are finished": "കൊള്ളാം, ഞങ്ങൾ പൂർത്തിയാക്കി"},
        "mr-IN": {"Hello": "नमस्कार", "Welcome": "स्वागत आहे", "Look at the numbers": "संख्या पहा", "Now tell me what is missing": "आता सांगा काय गहाळ आहे", "Great, we are finished": "छान, आम्ही पूर्ण केले"},
        "ta-IN": {"Hello": "வணக்கம்", "Welcome": "வரவேற்பு", "Look at the numbers": "எண்களை பாருங்கள்", "Now tell me what is missing": "இப்போது எது காணவில்லை என்று சொல்லுங்கள்", "Great, we are finished": "நன்று, நாங்கள் முடித்துவிட்டோம்"},
        "te-IN": {"Hello": "నమస్కారం", "Welcome": "స్వాగతం", "Look at the numbers": "సంఖ్యలను చూడండి", "Now tell me what is missing": "ఇప్పుడు ఏది లేదు చెప్పండి", "Great, we are finished": "బాగుంది, మేము పూర్తి చేశాము"}
    }
    replacements = demo_all.get(target_language, demo_all["hi-IN"])
    translated = text
    for source, target in replacements.items():
        translated = translated.replace(source, target)
    return translated


def translate_text_bhashini(text: str, target_language: str, settings: Settings) -> str:
    """Translate one scene while preserving BalVibe pause markers verbatim."""
    if target_language in {"en-IN", "en-US"}:
        return text
    if settings.demo_mode:
        return _demo_translation(text, target_language)

    source_code = "en"
    target_code = _language_code(target_language)
    service_id, auth_name, auth_value, callback_url = _pipeline_config(
        source_code, target_code, settings
    )

    output: list[str] = []
    cursor = 0
    for match in PAUSE_RE.finditer(text):
        before = text[cursor:match.start()].strip()
        if before:
            for chunk in _split_text(before):
                output.append(
                    _compute_translation(
                        chunk,
                        source_code,
                        target_code,
                        service_id,
                        auth_name,
                        auth_value,
                        callback_url,
                    )
                )
        output.append(match.group(0))
        cursor = match.end()

    tail = text[cursor:].strip()
    if tail:
        for chunk in _split_text(tail):
            output.append(
                _compute_translation(
                    chunk,
                    source_code,
                    target_code,
                    service_id,
                    auth_name,
                    auth_value,
                    callback_url,
                )
            )

    return " ".join(output)
