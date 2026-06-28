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


DEMO_NAME = "Jamie Lee"
DEMO_DOB = "July 4, 2000"
DEMO_DOB_NUMERIC_SPOKEN = "zero seven, zero four, two thousand"
DEMO_CALLBACK_PHONE = "555-0142"


class PatientResponder:
    """LLM-first patient simulator for live assessment calls.

    This version removes the large deterministic scenario tree. The live caller
    uses an LLM for normal conversation so it can answer unexpected questions
    like a human. Only narrow intake facts stay hard-coded because those must be
    exact and fast: name, date of birth, phone number, days remaining, pharmacy,
    and a few obvious yes/no confirmations.
    """

    def __init__(self) -> None:
        self.settings = get_settings(require_twilio=False)
        self._client = None
        if self.settings.openai_api_key and self.settings.live_llm_responder:
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=self.settings.openai_api_key)
            except Exception:
                self._client = None

    def next_reply(self, scenario: Scenario, transcript: list[dict[str, Any]], turn_index: int) -> BotDecision:
        last_agent = last_text(transcript, "agent")
        agent = normalize(last_agent)
        patient_history = render_patient_text(transcript)
        patient_norm = normalize(patient_history)

        quick = exact_intake_reply(scenario.id, agent, patient_norm)
        if quick is not None:
            return self._finalize(quick, patient_norm, turn_index)

        if self._client is not None:
            decision = self._openai_reply(scenario, transcript, turn_index)
            return self._finalize(decision, patient_norm, turn_index)

        # Fallback only if no OpenAI API key is configured. It is intentionally
        # conservative because the high-quality submission path should use the
        # live LLM responder.
        return self._finalize(fallback_reply(scenario.id, agent, turn_index), patient_norm, turn_index)

    def _openai_reply(self, scenario: Scenario, transcript: list[dict[str, Any]], turn_index: int) -> BotDecision:
        last_agent = last_text(transcript, "agent")
        last_patient = last_text(transcript, "patient")
        transcript_text = render_transcript_for_prompt(transcript)
        profile = scenario_profile(scenario.id)

        instructions = f"""
You are Jamie Lee, a real patient speaking by phone to a healthcare voice agent.
You are not an evaluator, not a bot, and not a benchmark. Speak naturally.

Fixed demo identity:
- Name: {DEMO_NAME}
- Date of birth: {DEMO_DOB}
- If asked for DOB in numbers, say: {DEMO_DOB_NUMERIC_SPOKEN}
- Callback phone: if the agent offers a callback number already on file, confirm it as correct. Otherwise use {DEMO_CALLBACK_PHONE}.

Scenario facts and intent:
{profile}

How to choose the next reply:
1. First, identify the latest agent question or request.
2. Answer that exact latest question directly. Do not answer an older question.
3. Then add at most one short helpful detail if needed to move the task forward.
4. Speak like a polite patient in one short sentence, or two short sentences max.
5. Do not repeat the same wording as the previous patient turn.
6. Do not say "what would be the next best option" unless the agent clearly said the requested option is unavailable.
7. Do not say goodbye until the request is finished, the question is answered, or the agent clearly cannot help further.
8. If the agent is checking, processing, or saying "one moment" without asking a question, respond briefly with patience, e.g. "Okay, thank you." and keep done false.
9. If the agent asks for confirmation, answer yes/no clearly and include the specific thing being confirmed.
10. If the agent offers an appointment that meets the scenario constraints, accept it. If it does not meet the constraints, politely ask for the closest acceptable option.
11. If the agent asks for a pharmacy, provide the pharmacy from the scenario. Do not give a callback number as the pharmacy.
12. If the agent asks for days/doses left, provide the days/doses from the scenario.
13. If the agent asks about symptoms or urgency, provide the symptom/urgency facts from the scenario.
14. Never mention: goal, scenario, test, bot, benchmark, transcript, prompt, or AI debugging.
15. Never sound annoyed. Never say "I already gave" or anything similar.

Return strict JSON only:
{{"reply":"...","done":false,"notes":"short reason"}}
""".strip()

        user_input = f"""
Turn index: {turn_index}
Latest agent text: {last_agent}
Previous patient reply: {last_patient}

Recent transcript:
{transcript_text}

Give Jamie's next spoken reply now.
""".strip()

        try:
            response = self._client.responses.create(
                model=self.settings.openai_model,
                instructions=instructions,
                input=user_input,
                temperature=0.18,
                max_output_tokens=120,
            )
            raw = getattr(response, "output_text", "") or ""
            parsed = parse_json_loose(raw)
            reply = clean_for_speech(str(parsed.get("reply", "")))
            done = bool(parsed.get("done", False))
            notes = str(parsed.get("notes", ""))[:500]
            if not reply:
                raise ValueError(f"empty model reply: {raw!r}")
            return BotDecision(reply=reply, done=done, notes=f"llm: {notes}")
        except Exception as exc:
            return fallback_reply(scenario.id, normalize(last_agent), turn_index, notes=f"llm fallback: {exc}")

    def _finalize(self, decision: BotDecision, patient_norm: str, turn_index: int) -> BotDecision:
        reply = clean_for_speech(decision.reply)
        reply_norm = normalize(reply)
        done = decision.done
        notes = decision.notes

        forbidden = [
            "my goal",
            "scenario",
            "benchmark",
            "patient bot",
            "voice bot",
            "test line",
            "i already gave",
            "i think i already",
            "prompt",
            "transcript",
        ]
        if any(term in reply_norm for term in forbidden):
            reply = "Sorry, let me say that more clearly. I just need help with this request."
            done = False
            notes = f"sanitized forbidden wording: {notes}"

        # Exact repeats can happen when the other agent asks the same thing, but
        # repeated identical audio sounds broken. Ask the LLM output to be a
        # softer clarification instead of a rude close.
        if reply_norm and patient_norm.count(reply_norm) >= 1 and not done:
            reply = "Sorry, let me clarify. " + concise_scenario_clarification(reply, turn_index)
            reply = clean_for_speech(reply)
            done = False
            notes = f"softened repeated reply: {notes}"

        if turn_index >= self.settings.max_turns_per_call - 1 and not done:
            reply = "Thank you for your help. I will follow up with the office if needed. Goodbye."
            done = True
            notes = f"max turn close: {notes}"

        if done and "goodbye" not in normalize(reply):
            reply = reply.rstrip(".") + ". Thank you, goodbye."

        return BotDecision(reply=reply, done=done, notes=notes)


# --------------------------- exact intake helpers ---------------------------


def exact_intake_reply(scenario_id: str, agent: str, patient_norm: str) -> BotDecision | None:
    """Fast exact answers for fields that should not depend on model creativity."""
    if asks_identity(agent):
        return BotDecision("Yes, this is Jamie Lee.", False, "identity")

    if asks_name(agent):
        return BotDecision("My name is Jamie Lee.", False, "name")

    if asks_dob(agent):
        if contains_any(agent, "numbers", "numeric", "month day", "month, day", "mm", "example"):
            return BotDecision(f"My date of birth is {DEMO_DOB_NUMERIC_SPOKEN}.", False, "dob numeric")
        return BotDecision(f"Sure, my date of birth is {DEMO_DOB}.", False, "dob")

    if asks_callback_number(agent) and not asks_pharmacy(agent):
        if contains_any(agent, "is that correct", "correct", "best number", "number on file", "call back number as"):
            return BotDecision("Yes, that is the best callback number.", False, "callback confirmed")
        return BotDecision(f"My best callback number is {DEMO_CALLBACK_PHONE}.", False, "callback provided")

    if asks_pharmacy(agent):
        if scenario_id == "05_refill_urgent_symptom":
            return BotDecision("Please send it to Walgreens on Pine Street.", False, "pharmacy urgent refill")
        if scenario_id == "04_refill_normal":
            return BotDecision("Please send it to CVS on Main Street.", False, "pharmacy routine refill")

    if asks_days_left(agent):
        if scenario_id == "05_refill_urgent_symptom":
            return BotDecision("I have about one or two doses left.", False, "doses left")
        if scenario_id == "04_refill_normal":
            return BotDecision("I have two pills left, so about two days remaining.", False, "days left")

    return None


# ------------------------------ scenario facts ------------------------------


def scenario_profile(scenario_id: str) -> str:
    profiles = {
        "01_simple_schedule": "You want to schedule a new patient annual checkup. You prefer next Tuesday or Wednesday morning. You are open to the first available provider. If the agent says you already have this appointment, say you understand and ask to keep the current booking instead of creating a duplicate.",
        "02_reschedule": "You want to reschedule an existing appointment because of a work conflict. You prefer the following Monday after 2 PM. If Monday after 2 PM is unavailable, ask for the closest weekday afternoon after 2 PM. If the agent offers clinic follow-up, accept it.",
        "03_cancel": "You want to cancel an appointment and you do not want to reschedule today. If the agent asks which appointment, use the appointment it can see. If asked for a reason, say you have a work conflict. Confirm cancellation only when the agent asks.",
        "04_refill_normal": "You need a refill for lisinopril 10 milligrams once daily. You have two pills left, about two days. Pharmacy: CVS on Main Street. You have no symptoms or urgency. You want to know how long refills usually take if the agent brings up timing.",
        "05_refill_urgent_symptom": "You need an albuterol inhaler refill. You have one or two doses left. Pharmacy: Walgreens on Pine Street. You felt mildly short of breath after walking upstairs today. You do not have chest pain and it is not severe right now. If given urgent-care/911 advice, acknowledge it.",
        "06_office_hours_weekend": "You ask whether Sunday at 10 AM is available for a checkup. If Sunday is unavailable or closed, you prefer Monday or Tuesday morning. If those are unavailable, accept the next available weekday morning. Confirm booking when asked.",
        "07_insurance_question": "You have an insurance question before booking. Ask whether Aetna is accepted and whether you need a referral for an orthopedic specialist visit for knee pain. Do not update insurance today; just confirm whether you should check with Aetna.",
        "08_location_question": "You want to know which location has parking and wheelchair access before scheduling. Once the agent gives an address, ask it to repeat the address once slowly so you can write it down, then close politely.",
        "09_unclear_request": "Start vague with: I need to fix my thing from last time. When the agent asks a clarifying question, explain that you mean rescheduling your follow-up appointment. Prefer a weekday afternoon and accept a reasonable afternoon option.",
        "10_interruption_barge_in": "You need a same-week routine appointment, not urgent. You are in a hurry but polite. Prefer any weekday after 4 PM this week. If none are available, ask for early next week after 4 PM. Do not accept a time before 4 PM unless the agent says nothing later is available, in which case ask for later in the week or close politely.",
    }
    return profiles.get(scenario_id, "You are a polite patient asking for help from the clinic.")


# ------------------------------- fallback only ------------------------------


def fallback_reply(scenario_id: str, agent: str, turn_index: int, notes: str = "fallback") -> BotDecision:
    if asks_confirmation(agent):
        return BotDecision("Yes, that is correct.", False, notes)
    if asks_provider(agent):
        return BotDecision("I am open to any available provider.", False, notes)
    if asks_preferred_time(agent):
        return BotDecision("A weekday morning or afternoon would work, depending on the request.", False, notes)
    if asks_how_help(agent):
        return BotDecision(first_request_without_hi(scenario_id), False, notes)
    if turn_index >= 8:
        return BotDecision("Thank you for your help. I will follow up with the office if needed. Goodbye.", True, notes)
    return BotDecision(first_request_without_hi(scenario_id), False, notes)


def concise_scenario_clarification(reply: str, turn_index: int) -> str:
    # Use the non-repeated reply as a seed but make it sound like a clarification.
    reply = clean_for_speech(reply)
    reply = re.sub(r"^(yes,?\s*)", "", reply, flags=re.IGNORECASE).strip()
    if not reply:
        return "I still need help with this request."
    return reply[0].lower() + reply[1:]


# ------------------------------ text helpers ------------------------------


def first_request_without_hi(scenario_id: str) -> str:
    text = first_request(scenario_id)
    return re.sub(r"^hi,?\s*", "", text, flags=re.IGNORECASE).strip().capitalize()


def first_request(scenario_id: str) -> str:
    return {
        "01_simple_schedule": "Hi, I would like to schedule a new patient annual checkup.",
        "02_reschedule": "Hi, I need to reschedule my appointment because of a work conflict.",
        "03_cancel": "Hi, I need to cancel an appointment, and I do not want to reschedule today.",
        "04_refill_normal": "Hi, I am calling for a refill of my lisinopril 10 milligram prescription.",
        "05_refill_urgent_symptom": "Hi, I need a refill for my albuterol inhaler.",
        "06_office_hours_weekend": "Hi, can I come in Sunday at 10 AM for a checkup?",
        "07_insurance_question": "Hi, I have an insurance question before I book.",
        "08_location_question": "Hi, which location has parking and wheelchair access?",
        "09_unclear_request": "Hi, I need to fix my thing from last time.",
        "10_interruption_barge_in": "Hi, I need a same-week appointment.",
    }.get(scenario_id, "Hi, I need help with an appointment.")


def last_text(transcript: list[dict[str, Any]], speaker: str) -> str:
    for row in reversed(transcript):
        if row.get("speaker") == speaker:
            return str(row.get("text", ""))
    return ""


def render_patient_text(transcript: list[dict[str, Any]]) -> str:
    return "\n".join(str(row.get("text", "")) for row in transcript if row.get("speaker") == "patient")


def render_transcript_for_prompt(transcript: list[dict[str, Any]]) -> str:
    if not transcript:
        return "(No transcript yet.)"
    lines: list[str] = []
    for row in transcript[-18:]:
        speaker = row.get("speaker", "unknown").upper()
        text = row.get("text", "")
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def normalize(text: str) -> str:
    return clean_text(text).lower()


def contains_any(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def asks_identity(text: str) -> bool:
    stripped = text.strip(" .?!,;")
    if stripped in {"jamie", "amy", "janie", "janey", "cheney", "jenny"}:
        return True
    return bool(
        re.search(r"\b(am i|are you|is this|speaking with|with)\s+(jamie|amy|janie|janey|cheney|jenny)\b", text)
        or re.search(r"\bare you\s+(jamie|amy|janie|janey|cheney|jenny)\b", text)
        or contains_any(text, "may i verify your information, are you jamie")
    )


def asks_name(text: str) -> bool:
    return contains_any(text, "first and last name", "full name", "your name", "tell me your name")


def asks_dob(text: str) -> bool:
    return contains_any(text, "date of birth", "day of birth", "dob", "birthday", "data birth", "birth and numbers")


def asks_callback_number(text: str) -> bool:
    return contains_any(text, "callback", "call back", "best number", "number on file", "number is", "correct for a call")


def asks_pharmacy(text: str) -> bool:
    return contains_any(
        text,
        "pharmacy",
        "where you want your medication",
        "where should",
        "send it to",
        "medication sent",
        "name of the pharmacy",
    )


def asks_days_left(text: str) -> bool:
    return contains_any(text, "how many days", "days of", "do you have left", "are you out", "already out", "doses left", "pills left", "have left") and contains_any(text, "lisinopril", "albuterol", "inhaler", "medication", "pills", "doses")


def asks_confirmation(text: str) -> bool:
    return contains_any(text, "is that correct", "is that right", "correct?", "to confirm", "just to confirm", "confirm you", "confirm that")


def asks_provider(text: str) -> bool:
    return contains_any(text, "specific provider", "first available", "any available provider", "provider you'd like", "doctor you'd like")


def asks_preferred_time(text: str) -> bool:
    return contains_any(text, "preferred day", "preferred time", "what day", "what time", "time of day", "availability", "when would")


def asks_how_help(text: str) -> bool:
    return contains_any(text, "how can i help", "how may i help", "what can i help", "what would you like", "how can i assist", "what do you need help")


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
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return {"reply": raw, "done": False, "notes": "non-json model output"}


def clean_for_speech(text: str) -> str:
    text = clean_text(text)
    text = text.replace("[", "").replace("]", "")
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 340:
        text = text[:337].rsplit(" ", 1)[0] + "..."
    return text


# Backward-compatible helper from the original repo.
def extract_fact(facts: str, label: str) -> str | None:
    pattern = rf"{re.escape(label)}:\s*([^.;]+)"
    match = re.search(pattern, facts)
    if not match:
        return None
    return match.group(1).strip()
