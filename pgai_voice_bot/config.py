from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
CALLS_DIR = DATA_DIR / "calls"
DELIVERABLES_DIR = PROJECT_ROOT / "deliverables"

DEFAULT_ASSESSMENT_NUMBER = "+18054398008"


@dataclass(frozen=True)
class Settings:
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_from_number: str
    public_base_url: str
    assessment_number: str = DEFAULT_ASSESSMENT_NUMBER
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    max_turns_per_call: int = 10
    twilio_voice: str = "Polly.Joanna-Neural"
    speech_gather_timeout_seconds: int = 10


def get_settings(require_twilio: bool = False) -> Settings:
    settings = Settings(
        twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
        twilio_from_number=os.getenv("TWILIO_FROM_NUMBER", ""),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
        assessment_number=os.getenv("ASSESSMENT_NUMBER", DEFAULT_ASSESSMENT_NUMBER),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        max_turns_per_call=int(os.getenv("MAX_TURNS_PER_CALL", "10")),
        twilio_voice=os.getenv("TWILIO_VOICE", "Polly.Joanna-Neural"),
        speech_gather_timeout_seconds=int(os.getenv("SPEECH_GATHER_TIMEOUT_SECONDS", "10")),
    )

    if settings.assessment_number != DEFAULT_ASSESSMENT_NUMBER:
        raise ValueError(
            f"Refusing to run: ASSESSMENT_NUMBER must remain {DEFAULT_ASSESSMENT_NUMBER}. "
            "This challenge requires calls only to the official test number."
        )

    if require_twilio:
        missing = []
        if not settings.twilio_account_sid:
            missing.append("TWILIO_ACCOUNT_SID")
        if not settings.twilio_auth_token:
            missing.append("TWILIO_AUTH_TOKEN")
        if not settings.twilio_from_number:
            missing.append("TWILIO_FROM_NUMBER")
        if not settings.public_base_url:
            missing.append("PUBLIC_BASE_URL")
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    return settings


def ensure_dirs() -> None:
    CALLS_DIR.mkdir(parents=True, exist_ok=True)
    (DELIVERABLES_DIR / "transcripts").mkdir(parents=True, exist_ok=True)
    (DELIVERABLES_DIR / "recordings").mkdir(parents=True, exist_ok=True)
    (DELIVERABLES_DIR / "bug_reports").mkdir(parents=True, exist_ok=True)
