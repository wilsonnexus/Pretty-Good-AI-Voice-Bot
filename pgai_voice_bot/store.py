from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import CALLS_DIR, ensure_dirs


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def call_dir(call_sid: str) -> Path:
    ensure_dirs()
    safe = "".join(ch for ch in call_sid if ch.isalnum() or ch in "-_")
    path = CALLS_DIR / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_path(call_sid: str) -> Path:
    return call_dir(call_sid) / "state.json"


def transcript_jsonl_path(call_sid: str) -> Path:
    return call_dir(call_sid) / "transcript.jsonl"


def transcript_txt_path(call_sid: str) -> Path:
    return call_dir(call_sid) / "transcript.txt"


def metadata_path(call_sid: str) -> Path:
    return call_dir(call_sid) / "metadata.json"


def load_state(call_sid: str) -> dict[str, Any]:
    path = state_path(call_sid)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(call_sid: str, state: dict[str, Any]) -> None:
    path = state_path(call_sid)
    state["updated_at"] = utc_now_iso()
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def update_metadata(call_sid: str, **fields: Any) -> None:
    path = metadata_path(call_sid)
    current: dict[str, Any] = {}
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
    current.update(fields)
    current["updated_at"] = utc_now_iso()
    path.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")


def append_turn(call_sid: str, speaker: str, text: str, turn_index: int | None = None, confidence: str | None = None) -> None:
    entry = {
        "timestamp": utc_now_iso(),
        "speaker": speaker,
        "text": clean_text(text),
    }
    if turn_index is not None:
        entry["turn_index"] = turn_index
    if confidence is not None:
        entry["confidence"] = confidence

    jsonl = transcript_jsonl_path(call_sid)
    with jsonl.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    prefix = "PATIENT BOT" if speaker.lower().startswith("patient") else "PGAI AGENT"
    with transcript_txt_path(call_sid).open("a", encoding="utf-8") as f:
        f.write(f"[{entry['timestamp']}] {prefix}: {entry['text']}\n")


def read_transcript(call_sid: str) -> list[dict[str, Any]]:
    path = transcript_jsonl_path(call_sid)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def clean_text(text: str) -> str:
    text = (text or "").strip()
    text = " ".join(text.split())
    return text


def all_call_dirs() -> list[Path]:
    ensure_dirs()
    return sorted([p for p in CALLS_DIR.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime)
