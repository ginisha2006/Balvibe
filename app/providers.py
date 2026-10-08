from __future__ import annotations

import base64
import html
import json
import re
import time
from typing import Any

import requests

from .audio import concatenate_wavs, silence_wav, tone_wav
from .config import Settings

PAUSE_RE = re.compile(r"\[PAUSE(?:\s+(\d+(?:\.\d+)?)\s*(?:seconds?|s)?)?\]", re.IGNORECASE)

AZURE_VOICES: dict[str, list[dict[str, str]]] = {
    "bn-IN": [{"id": "bn-IN-TanishaaNeural", "label": "Tanishaa · Female"}, {"id": "bn-IN-BashkarNeural", "label": "Bashkar · Male"}],
    "gu-IN": [{"id": "gu-IN-DhwaniNeural", "label": "Dhwani · Female"}, {"id": "gu-IN-NiranjanNeural", "label": "Niranjan · Male"}],
    "hi-IN": [{"id": "hi-IN-SwaraNeural", "label": "Swara · Female"}, {"id": "hi-IN-MadhurNeural", "label": "Madhur · Male"}],
    "kn-IN": [{"id": "kn-IN-SapnaNeural", "label": "Sapna · Female"}, {"id": "kn-IN-GaganNeural", "label": "Gagan · Male"}],
    "ml-IN": [{"id": "ml-IN-SobhanaNeural", "label": "Sobhana · Female"}, {"id": "ml-IN-MidhunNeural", "label": "Midhun · Male"}],
    "mr-IN": [{"id": "mr-IN-AarohiNeural", "label": "Aarohi · Female"}, {"id": "mr-IN-ManoharNeural", "label": "Manohar · Male"}],
    "ta-IN": [{"id": "ta-IN-PallaviNeural", "label": "Pallavi · Female"}, {"id": "ta-IN-ValluvarNeural", "label": "Valluvar · Male"}],
    "te-IN": [{"id": "te-IN-ShrutiNeural", "label": "Shruti · Female"}, {"id": "te-IN-MohanNeural", "label": "Mohan · Male"}],
    "en-IN": [{"id": "en-IN-NeerjaNeural", "label": "Neerja · Female"}, {"id": "en-IN-PrabhatNeural", "label": "Prabhat · Male"}],
}
SARVAM_VOICES = [
    {"id": "shubh", "label": "Shubh · Male"},
    {"id": "ritu", "label": "Ritu · Female"},
    {"id": "priya", "label": "Priya · Female"},
    {"id": "aditya", "label": "Aditya · Male"},
]


def provider_config() -> dict[str, Any]:
    return {
        "languages": [
            {"id": "hi-IN", "label": "Hindi · India"},
            {"id": "bn-IN", "label": "Bengali · India"},
            {"id": "gu-IN", "label": "Gujarati · India"},
            {"id": "kn-IN", "label": "Kannada · India"},
            {"id": "ml-IN", "label": "Malayalam · India"},
            {"id": "mr-IN", "label": "Marathi · India"},
            {"id": "ta-IN", "label": "Tamil · India"},
            {"id": "te-IN", "label": "Telugu · India"},
            {"id": "en-IN", "label": "English · India"},
        ],
        "translationProviders": {
            "sarvam": {
                "label": "Sarvam Translate",
                "description": "Sarvam's Indic translation API",
            },
            "bhashini": {
                "label": "BHASHINI / ULCA",
                "description": "Government of India language technology pipeline",
            },
        },
        "ttsProviders": {
            "azure": {"label": "Microsoft Azure Speech", "voices": AZURE_VOICES},
            "sarvam": {"label": "Sarvam Bulbul v3", "voices": {lang: SARVAM_VOICES for lang in ["hi-IN", "bn-IN", "gu-IN", "kn-IN", "ml-IN", "mr-IN", "ta-IN", "te-IN", "en-IN"]}},
        },
    }


def _split_text(text: str, max_len: int) -> list[str]:
    chunks: list[str] = []
    remaining = text.strip()
    while len(remaining) > max_len:
        cut = remaining.rfind(".", 0, max_len)
        if cut < int(max_len * 0.55):
            cut = remaining.rfind(" ", 0, max_len)
        if cut < 1:
            cut = max_len
        include = 1 if cut < len(remaining) and remaining[cut:cut+1] == "." else 0
        chunks.append(remaining[: cut + include].strip())
        remaining = remaining[cut + include :].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def translate_text_sarvam(text: str, target_language: str, settings: Settings) -> str:
    if target_language in {"en-IN", "en-US"}:
        return text
    if settings.demo_mode:
        # Explicitly labeled deterministic demo translation used only for local/UI verification.
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
        demo = demo_all.get(target_language, demo_all["hi-IN"])
        translated = text
        for source, target in demo.items():
            translated = translated.replace(source, target)
        return translated
    if not settings.sarvam_api_key:
        raise RuntimeError("SARVAM_API_KEY is required for translation.")

    out: list[str] = []
    cursor = 0
    for match in PAUSE_RE.finditer(text):
        before = text[cursor:match.start()].strip()
        if before:
            out.append(_translate_sarvam_chunks(before, target_language, settings))
        out.append(match.group(0))
        cursor = match.end()
    tail = text[cursor:].strip()
    if tail:
        out.append(_translate_sarvam_chunks(tail, target_language, settings))
    return " ".join(out)


def _translate_sarvam_chunks(text: str, target_language: str, settings: Settings) -> str:
    translated: list[str] = []
    for chunk in _split_text(text, 1800):
        response = requests.post(
            "https://api.sarvam.ai/translate",
            headers={"api-subscription-key": settings.sarvam_api_key, "content-type": "application/json"},
            json={
                "input": chunk,
                "source_language_code": "en-IN",
                "target_language_code": target_language,
                "model": "sarvam-translate:v1",
                "mode": "formal",
            },
            timeout=60,
        )
        if not response.ok:
            raise RuntimeError(f"Sarvam translation failed ({response.status_code}): {response.text[:500]}")
        body = response.json()
        value = body.get("translated_text")
        if not value:
            raise RuntimeError("Sarvam translation returned no translated_text.")
        translated.append(value)
    return " ".join(translated)


def synthesize(provider: str, text: str, language: str, voice: str, settings: Settings) -> bytes:
    if provider == "azure":
        return synthesize_azure(text, language, voice, settings)
    if provider == "sarvam":
        return synthesize_sarvam(text, language, voice, settings)
    raise ValueError("tts provider must be 'azure' or 'sarvam'.")


def synthesize_azure(text: str, language: str, voice: str, settings: Settings) -> bytes:
    valid = {item["id"] for item in AZURE_VOICES.get(language, [])}
    if voice not in valid:
        raise ValueError(f"Unsupported Azure voice {voice!r} for {language}.")
    if settings.demo_mode:
        seconds = max(0.8, min(8.0, len(PAUSE_RE.sub("", text).split()) * 0.34))
        pause_seconds = sum(float(m.group(1) or 1) for m in PAUSE_RE.finditer(text))
        return tone_wav(seconds + pause_seconds, 260.0)
    if not settings.azure_speech_key:
        raise RuntimeError("AZURE_SPEECH_KEY is required for Azure voiceover.")

    pieces: list[str] = []
    cursor = 0
    for match in PAUSE_RE.finditer(text):
        spoken = text[cursor:match.start()].strip()
        if spoken:
            pieces.append(html.escape(spoken))
        ms = max(100, round(float(match.group(1) or 1) * 1000))
        pieces.append(f'<break time="{ms}ms"/>')
        cursor = match.end()
    tail = text[cursor:].strip()
    if tail:
        pieces.append(html.escape(tail))
    ssml = (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{language}">'
        f'<voice name="{voice}"><prosody rate="-5%">{" ".join(pieces)}</prosody></voice></speak>'
    )
    endpoint = f"https://{settings.azure_speech_region}.tts.speech.microsoft.com/cognitiveservices/v1"
    response = requests.post(
        endpoint,
        headers={
            "Ocp-Apim-Subscription-Key": settings.azure_speech_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
            "User-Agent": "BalVibe-Studio",
        },
        data=ssml.encode("utf-8"),
        timeout=90,
    )
    if not response.ok:
        raise RuntimeError(f"Azure TTS failed ({response.status_code}): {response.text[:500]}")
    return response.content


def synthesize_sarvam(text: str, language: str, voice: str, settings: Settings) -> bytes:
    valid = {item["id"] for item in SARVAM_VOICES}
    if voice not in valid:
        raise ValueError(f"Unsupported Sarvam voice {voice!r}.")
    if settings.demo_mode:
        seconds = max(0.8, min(8.0, len(PAUSE_RE.sub("", text).split()) * 0.33))
        pause_seconds = sum(float(m.group(1) or 1) for m in PAUSE_RE.finditer(text))
        return tone_wav(seconds + pause_seconds, 185.0)
    if not settings.sarvam_api_key:
        raise RuntimeError("SARVAM_API_KEY is required for Sarvam voiceover.")

    segments: list[bytes] = []
    cursor = 0
    for match in PAUSE_RE.finditer(text):
        spoken = text[cursor:match.start()].strip()
        if spoken:
            segments.extend(_sarvam_spoken_chunks(spoken, language, voice, settings))
        segments.append(silence_wav(float(match.group(1) or 1)))
        cursor = match.end()
    tail = text[cursor:].strip()
    if tail:
        segments.extend(_sarvam_spoken_chunks(tail, language, voice, settings))
    if not segments:
        raise ValueError("Scene has no speakable text.")
    return concatenate_wavs(segments)


def _sarvam_spoken_chunks(text: str, language: str, voice: str, settings: Settings) -> list[bytes]:
    audio: list[bytes] = []
    for chunk in _split_text(text, 2400):
        response = requests.post(
            "https://api.sarvam.ai/text-to-speech",
            headers={"api-subscription-key": settings.sarvam_api_key, "content-type": "application/json"},
            json={
                "text": chunk,
                "language_code": language,
                "model": "bulbul:v3",
                "speaker": voice,
                "speech_sample_rate": 24000,
                "output_audio_codec": "wav",
                "pace": 0.95,
                "temperature": 0.55,
            },
            timeout=90,
        )
        if not response.ok:
            raise RuntimeError(f"Sarvam TTS failed ({response.status_code}): {response.text[:500]}")
        body = response.json()
        encoded = (body.get("audios") or [None])[0]
        if not encoded:
            raise RuntimeError("Sarvam TTS returned no audio.")
        audio.append(base64.b64decode(encoded))
    return audio


def call_groq_json(system: str, user: str, settings: Settings, max_tokens: int | None = None) -> dict[str, Any]:
    if settings.demo_mode:
        raise RuntimeError("Demo generation is handled by the pipeline, not Groq.")
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is required for storyline and script generation.")

    # Keep one BalVibe generation inside low/free-tier Groq output-token budgets.
    actual_tokens = max_tokens or min(max(256, settings.groq_max_tokens), 1200)
    last_response: requests.Response | None = None

    for attempt in range(6):
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.groq_api_key}", "Content-Type": "application/json"},
            json={
                "model": settings.groq_model,
                "temperature": 0.35,
                "max_completion_tokens": actual_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=90,
        )
        last_response = response
        if response.ok:
            body = response.json()
            content = body.get("choices", [{}])[0].get("message", {}).get("content")
            if not content:
                raise RuntimeError("Groq returned an empty response.")
            try:
                return json.loads(content)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Groq returned invalid JSON: {content[:700]}") from exc

        if response.status_code != 429 or attempt == 5:
            raise RuntimeError(f"Groq generation failed ({response.status_code}): {response.text[:700]}")

        # Groq may return Retry-After, or include "try again in 4.26s" in the body.
        wait_seconds = 5.0
        header_wait = response.headers.get("retry-after")
        if header_wait:
            try:
                wait_seconds = max(wait_seconds, float(header_wait))
            except ValueError:
                pass
        match = re.search(r"try again in\s+([0-9.]+)s", response.text, re.I)
        if match:
            wait_seconds = max(wait_seconds, float(match.group(1)))
        time.sleep(min(wait_seconds + 0.5, 65.0))

    assert last_response is not None
    raise RuntimeError(f"Groq generation failed ({last_response.status_code}): {last_response.text[:700]}")
