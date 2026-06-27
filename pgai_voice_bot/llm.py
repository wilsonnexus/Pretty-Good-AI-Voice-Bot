from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .config import get_settings
from .scenarios import Scenario
from .store import clean_text


@dataclass(frozen=True)
class BotDecision:
    reply: str
    done: bool
    notes: str = ""


class PatientResponder:
    """Generates concise, natural patient replies.

    Uses OpenAI when OPENAI_API_KEY is set. Otherwise it falls back to simple scripted
    replies so that local smoke tests still work without paid APIs.
    """

    def __init__(self) -> None:
        self.settings = get_settings(require_twilio=False)
        self._client = None
        if self.settings.openai_api_key:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.settings.openai_api_key)

    def next_reply(self, scenario: Scenario, transcript: list[dict[str, Any]], turn_index: int) -> BotDecision:
        if self._client is None:
            return self._fallback_reply(scenario, transcript, turn_index)
        return self._openai_reply(scenario, transcript, turn_index)

    def _openai_reply(self, scenario: Scenario, transcript: list[dict[str, Any]], turn_index: int) -> BotDecision:
        instructions = f"""
You are a voice-bot patient simulator for an authorized assessment of Pretty Good AI's healthcare voice agent.
You are allowed to call only the provided assessment line. Act as the patient, not as the assistant.

Scenario title: {scenario.title}
Persona: {scenario.persona}
Goal: {scenario.goal}
Patient facts: {scenario.patient_facts}
First-reply strategy: {scenario.first_reply_strategy}
Edge case to test: {scenario.edge_case}
Success criteria: {scenario.success_criteria}

Rules for the spoken reply:
- Reply only as the patient.
- Keep it natural, realistic, and short: usually 1 sentence, at most 2 sentences.
- Do not say you are a bot, benchmark, evaluator, transcript, or test unless directly necessary.
- Do not provide private real data; use only the synthetic facts above.
- Actively steer the conversation toward the scenario goal.
- If the agent asks for info that is in Patient facts, provide it.
- If the agent misunderstands, correct it politely.
- If the scenario goal is complete or the agent has clearly reached a handoff/limitation, say a natural closing and set done true.
- Stop after a reasonable full conversation. If turn_index >= 7, close the call naturally and set done true.

Return strict JSON with keys: reply, done, notes.
""".strip()

        transcript_text = render_transcript_for_prompt(transcript)
        user_input = f"Current turn_index: {turn_index}\nConversation so far:\n{transcript_text}\n\nChoose the next patient reply."
        try:
            response = self._client.responses.create(
                model=self.settings.openai_model,
                instructions=instructions,
                input=user_input,
                temperature=0.4,
                max_output_tokens=220,
            )
            raw = getattr(response, "output_text", "") or ""
            parsed = parse_json_loose(raw)
            reply = clean_for_speech(parsed.get("reply", ""))
            done = bool(parsed.get("done", False))
            notes = str(parsed.get("notes", ""))[:500]
            if not reply:
                raise ValueError(f"Empty reply from model. Raw={raw!r}")
            return BotDecision(reply=reply, done=done, notes=notes)
        except Exception as exc:  # Keep the call alive even if the LLM/API fails.
            fallback = self._fallback_reply(scenario, transcript, turn_index)
            return BotDecision(
                reply=fallback.reply,
                done=fallback.done,
                notes=f"LLM fallback because of error: {exc}",
            )

    def _fallback_reply(self, scenario: Scenario, transcript: list[dict[str, Any]], turn_index: int) -> BotDecision:
        lower_agent_text = " ".join(
            row.get("text", "").lower() for row in transcript if row.get("speaker") == "agent"
        )
        if turn_index == 0:
            return BotDecision(reply=f"Hi, {scenario.first_reply_strategy}", done=False)
        if "date of birth" in lower_agent_text or "dob" in lower_agent_text:
            dob = extract_fact(scenario.patient_facts, "DOB") or "January 12, 1990"
            return BotDecision(reply=f"My date of birth is {dob}.", done=False)
        if "name" in lower_agent_text:
            name = extract_fact(scenario.patient_facts, "Name") or "Alex Morgan"
            return BotDecision(reply=f"My name is {name}.", done=False)
        if "phone" in lower_agent_text:
            phone = extract_fact(scenario.patient_facts, "Phone") or "555-0100"
            return BotDecision(reply=f"The best callback number is {phone}.", done=False)
        if "insurance" in lower_agent_text:
            insurance = extract_fact(scenario.patient_facts, "Insurance") or "I am not sure."
            return BotDecision(reply=f"My insurance is {insurance}.", done=False)
        if turn_index >= 6:
            return BotDecision(reply="Thank you, that helps. I appreciate it. Goodbye.", done=True)
        return BotDecision(
            reply=f"That sounds good. My goal is: {scenario.goal} Can you help me with that?",
            done=False,
        )


def extract_fact(facts: str, label: str) -> str | None:
    pattern = rf"{re.escape(label)}:\s*([^.;]+)"
    match = re.search(pattern, facts)
    if not match:
        return None
    return match.group(1).strip()


def render_transcript_for_prompt(transcript: list[dict[str, Any]]) -> str:
    if not transcript:
        return "(No transcript yet.)"
    lines: list[str] = []
    for row in transcript[-18:]:
        speaker = row.get("speaker", "unknown").upper()
        text = row.get("text", "")
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def parse_json_loose(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return {"reply": raw, "done": False, "notes": "non-json model output"}


def clean_for_speech(text: str) -> str:
    text = clean_text(text)
    text = text.replace("[", "").replace("]", "")
    # Twilio <Say> reads symbols awkwardly; make it plain spoken English.
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 420:
        text = text[:417].rsplit(" ", 1)[0] + "..."
    return text
