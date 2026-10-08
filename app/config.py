from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    demo_mode: bool
    groq_api_key: str
    groq_model: str
    groq_max_tokens: int
    sarvam_api_key: str
    bhashini_user_id: str
    bhashini_api_key: str
    bhashini_pipeline_id: str
    bhashini_ulca_config_endpoint: str
    bhashini_inference_url: str
    azure_speech_key: str
    azure_speech_region: str


def load_settings() -> Settings:
    data_dir = Path(os.getenv("BALVIBE_DATA_DIR", "./data")).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        data_dir=data_dir,
        demo_mode=os.getenv("BALVIBE_DEMO_MODE", "false").lower() in {"1", "true", "yes", "on"},
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        groq_model=os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b").strip(),
        groq_max_tokens=int(os.getenv("GROQ_MAX_TOKENS", "2400")),
        sarvam_api_key=os.getenv("SARVAM_API_KEY", "").strip(),
        bhashini_user_id=os.getenv("BHASHINI_USER_ID", "").strip(),
        bhashini_api_key=os.getenv("BHASHINI_API_KEY", "").strip(),
        bhashini_pipeline_id=os.getenv("BHASHINI_PIPELINE_ID", "64392f96daac500b55c543cd").strip(),
        bhashini_ulca_config_endpoint=os.getenv(
            "BHASHINI_ULCA_CONFIG_ENDPOINT",
            "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline",
        ).strip(),
        bhashini_inference_url=os.getenv(
            "BHASHINI_INFERENCE_URL",
            "https://dhruva-api.bhashini.gov.in/services/inference/pipeline",
        ).strip(),
        azure_speech_key=os.getenv("AZURE_SPEECH_KEY", "").strip(),
        azure_speech_region=os.getenv("AZURE_SPEECH_REGION", "centralindia").strip(),
    )
