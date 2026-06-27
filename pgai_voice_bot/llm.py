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
DEMO_PHONE = "555-0142"


class PatientResponder:
    """Scenario-aware patient responder for the assessment calls.

    The first version of this project used a very simple fallback that looked at
    the entire conversation. Once the agent asked for date of birth, the fallback
    kept repeating the DOB on every turn. That made the caller sound like a test
    script instead of a patient.

    This version is intentionally deterministic for voice-call quality. It looks
    only at the agent's latest turn, tracks what the patient has already said,
    and returns short patient-like replies that keep each scenario moving.
    OpenAI is still used by analyze_bugs.py, but live patient replies do not rely
    on an LLM API call during the phone conversation.
    """

    def __init__(self) -> None:
        self.settings = get_settings(require_twilio=False)

    def next_reply(self, scenario: Scenario, transcript: list[dict[str, Any]], turn_index: int) -> BotDecision:
        return self._scripted_reply(scenario, transcript, turn_index)

    def _scripted_reply(self, scenario: Scenario, transcript: list[dict[str, Any]], turn_index: int) -> BotDecision:
        last_agent = last_text(transcript, "agent")
        last_agent_l = normalize(last_agent)
        patient_text = "\n".join(row.get("text", "") for row in transcript if row.get("speaker") == "patient")
        patient_l = normalize(patient_text)

        # First patient turn: never expose scenario instructions like "my goal is".
        if not patient_text.strip() or turn_index == 0:
            return BotDecision(first_request(scenario.id), False, "first request")

        # Identity and verification questions should be answered directly, then
        # immediately steer back to the scenario if the same question repeats.
        if asks_if_speaking_to_jamie(last_agent_l):
            return BotDecision("Yes, this is Jamie Lee.", False, "identity confirmation")

        if asks_name(last_agent_l):
            return BotDecision("My name is Jamie Lee.", False, "name provided")

        if asks_dob(last_agent_l):
            if count_mentions(patient_l, "july 4") >= 1:
                return BotDecision(f"It is {DEMO_DOB}. {scenario_request(scenario.id)}", False, "dob repeated with intent")
            return BotDecision(f"Sure, my date of birth is {DEMO_DOB}.", False, "dob provided")

        if asks_phone(last_agent_l):
            return BotDecision(f"The best callback number is {DEMO_PHONE}.", False, "phone provided")

        if no_clear_speech(last_agent_l):
            return BotDecision(scenario_request(scenario.id), False, "agent did not hear clearly")

        # Scenario-specific handlers. These come after identity checks so the bot
        # behaves like a real patient going through intake.
        if scenario.id == "01_simple_schedule":
            return handle_simple_schedule(last_agent_l, patient_l, turn_index)
        if scenario.id == "02_reschedule":
            return handle_reschedule(last_agent_l, patient_l, turn_index)
        if scenario.id == "03_cancel":
            return handle_cancel(last_agent_l, patient_l, turn_index)
        if scenario.id == "04_refill_normal":
            return handle_refill_normal(last_agent_l, patient_l, turn_index)
        if scenario.id == "05_refill_urgent_symptom":
            return handle_refill_urgent(last_agent_l, patient_l, turn_index)
        if scenario.id == "06_office_hours_weekend":
            return handle_weekend_hours(last_agent_l, patient_l, turn_index)
        if scenario.id == "07_insurance_question":
            return handle_insurance(last_agent_l, patient_l, turn_index)
        if scenario.id == "08_location_question":
            return handle_location(last_agent_l, patient_l, turn_index)
        if scenario.id == "09_unclear_request":
            return handle_unclear(last_agent_l, patient_l, turn_index)
        if scenario.id == "10_interruption_barge_in":
            return handle_interruption(last_agent_l, patient_l, turn_index)

        if turn_index >= 6:
            return BotDecision("Thank you, that helps. Goodbye.", True, "max turns")
        return BotDecision(scenario_request(scenario.id), False, "default scenario request")


# ----------------------------- scenario handlers -----------------------------


def handle_simple_schedule(agent: str, patient: str, turn_index: int) -> BotDecision:
    if asks_how_help(agent) or asks_appointment_type(agent) or contains_any(agent, "what type", "what brings you"):
        return BotDecision("I would like to schedule a new patient annual checkup.", False, "appointment type")
    if contains_any(agent, "urgent", "pain", "injury", "emergency"):
        return BotDecision("It is not urgent. It is just a routine annual checkup.", False, "non urgent")
    if contains_any(agent, "when", "date", "time", "availability", "prefer"):
        return BotDecision("Next Tuesday or Wednesday morning would be best if either is available.", False, "availability")
    if contains_any(agent, "confirm", "scheduled", "booked", "appointment is"):
        return BotDecision("That works for me. Thank you, goodbye.", True, "confirmed")
    return close_or_repeat("I would like to book a new patient annual checkup, preferably next Tuesday or Wednesday morning.", turn_index)


def handle_reschedule(agent: str, patient: str, turn_index: int) -> BotDecision:
    if contains_any(agent, "no appointment", "no appointments", "don't have", "do not have", "unable to proceed"):
        return BotDecision("Okay, I understand. I was trying to move my Friday 3 PM appointment to Monday after 2 PM. I can call the office if you cannot see it.", True, "limitation reached")
    if contains_any(agent, "book a new", "schedule a new", "new appointment instead"):
        return BotDecision("No thank you. I do not want a new appointment. I only want to reschedule my existing Friday 3 PM appointment.", False, "reject new appointment")
    if contains_any(agent, "current", "existing", "which appointment", "what appointment"):
        return BotDecision("It is my Friday 3 PM appointment with Dr. Patel.", False, "current appointment")
    if contains_any(agent, "when", "date", "time", "availability", "move"):
        return BotDecision("I need to move it to the following Monday after 2 PM.", False, "new time")
    if asks_how_help(agent):
        return BotDecision("I need to reschedule my Friday 3 PM appointment because of a work conflict.", False, "reschedule request")
    if contains_any(agent, "confirm", "rescheduled", "changed"):
        return BotDecision("Thank you, that works. Goodbye.", True, "confirmed")
    return close_or_repeat("I need to reschedule my Friday 3 PM appointment to the following Monday after 2 PM.", turn_index)


def handle_cancel(agent: str, patient: str, turn_index: int) -> BotDecision:
    if contains_any(agent, "new appointment", "book", "reschedule", "schedule") and contains_any(agent, "would you like", "instead", "right now"):
        return BotDecision("No thank you. I only want to cancel the appointment and I do not want to reschedule today.", False, "decline reschedule")
    if contains_any(agent, "no appointment", "no appointments", "don't have", "do not have"):
        return BotDecision("Okay, thank you for checking. I will call back if needed. Goodbye.", True, "no appointment")
    if asks_how_help(agent) or contains_any(agent, "what would you like"):
        return BotDecision("I need to cancel my dermatology appointment for next Thursday at 9 AM, and I do not want to reschedule today.", False, "cancel request")
    if contains_any(agent, "confirm", "cancelled", "canceled"):
        return BotDecision("Thank you for confirming. Goodbye.", True, "cancel confirmed")
    return close_or_repeat("Please cancel my dermatology appointment for next Thursday at 9 AM. I do not want to reschedule today.", turn_index)


def handle_refill_normal(agent: str, patient: str, turn_index: int) -> BotDecision:
    if contains_any(agent, "refill", "prescription") and contains_any(agent, "dosage", "dose", "question about"):
        return BotDecision("I am asking for a refill of lisinopril 10 milligrams, once daily.", False, "refill not dosage advice")
    if contains_any(agent, "dosage", "dose", "what medication", "which medication", "medication"):
        return BotDecision("It is lisinopril 10 milligrams, once daily.", False, "medication details")
    if contains_any(agent, "pharmacy"):
        return BotDecision("Please send it to CVS on Main Street.", False, "pharmacy")
    if contains_any(agent, "symptom", "urgent", "side effect", "emergency"):
        return BotDecision("No symptoms. This is just a routine refill, and I have two pills left.", False, "no symptoms")
    if asks_how_help(agent) or contains_any(agent, "refill", "prescription"):
        if "how long" not in patient:
            return BotDecision("I need a refill for lisinopril 10 milligrams. I have two pills left, and I use CVS on Main Street. How long does it usually take?", False, "refill request")
        return BotDecision("I just want to know how long the refill usually takes.", False, "timing question")
    if contains_any(agent, "sent", "requested", "submitted", "provider", "24", "48"):
        return BotDecision("Thank you, that answers my question. Goodbye.", True, "refill complete")
    return close_or_repeat("I need a refill for lisinopril 10 milligrams and want to know how long it usually takes.", turn_index)


def handle_refill_urgent(agent: str, patient: str, turn_index: int) -> BotDecision:
    if contains_any(agent, "chest pain", "severe", "911", "emergency", "urgent care"):
        return BotDecision("I do not have chest pain and I am not in severe distress, but I want to know what to do if the shortness of breath gets worse.", False, "triage answer")
    if contains_any(agent, "appointment", "provider", "discuss", "schedule"):
        return BotDecision("Yes, I can speak with a provider. Should I seek urgent care if the breathing gets worse before then?", False, "asks escalation guidance")
    if asks_how_help(agent) or contains_any(agent, "refill", "medication", "inhaler"):
        return BotDecision("I need a refill for my albuterol inhaler. I also felt mildly short of breath after walking upstairs today.", False, "refill with symptom")
    return close_or_repeat("I need an albuterol refill, and I had mild shortness of breath after walking upstairs.", turn_index)


def handle_weekend_hours(agent: str, patient: str, turn_index: int) -> BotDecision:
    if contains_any(agent, "closed", "not open", "weekday", "monday", "tuesday"):
        return BotDecision("Okay, if Sunday is not available, Monday or Tuesday morning works for me.", False, "accept weekday")
    if contains_any(agent, "when", "date", "time", "availability"):
        return BotDecision("I was hoping for Sunday at 10 AM. If the office is closed then, I can do Monday or Tuesday morning.", False, "weekend request")
    if asks_how_help(agent) or contains_any(agent, "what would you like"):
        return BotDecision("Can I come in Sunday at 10 AM for a checkup?", False, "sunday request")
    if contains_any(agent, "confirm", "scheduled", "booked"):
        return BotDecision("Thank you. Goodbye.", True, "confirmed")
    return close_or_repeat("I wanted to check if Sunday at 10 AM is available for a checkup.", turn_index)


def handle_insurance(agent: str, patient: str, turn_index: int) -> BotDecision:
    if contains_any(agent, "which type", "what type", "reason for the referral", "specialist"):
        return BotDecision("It would be for an orthopedic visit for knee pain. I mainly want to know if Aetna is accepted and if a referral is required.", False, "specialist type")
    if contains_any(agent, "insurance", "aetna", "referral") or asks_how_help(agent):
        if "aetna" not in patient:
            return BotDecision("Do you accept Aetna, and would I need a referral for an orthopedic specialist visit?", False, "insurance question")
        return BotDecision("Thanks. To be safe, should I also confirm the referral requirement with my insurance plan?", False, "verification question")
    if contains_any(agent, "anything else"):
        return BotDecision("No, that answers my question. Thank you, goodbye.", True, "complete")
    return close_or_repeat("I am calling to ask if you accept Aetna and whether I need a referral for an orthopedic specialist visit.", turn_index)


def handle_location(agent: str, patient: str, turn_index: int) -> BotDecision:
    if contains_any(agent, "address", "parking", "wheelchair", "accessible", "location") and contains_any(agent, "1234", "suite", "austin", "recovery"):
        if "repeat the address" not in patient:
            return BotDecision("Thank you. Could you repeat the address once slowly so I can write it down?", False, "ask repeat")
        return BotDecision("Got it. Thank you, that helps. Goodbye.", True, "location complete")
    if asks_how_help(agent) or contains_any(agent, "appointment", "something else", "what would you like"):
        return BotDecision("Before I schedule, I want to know which location has parking and wheelchair access.", False, "location question")
    return close_or_repeat("I am trying to find the office location with parking and wheelchair access before scheduling.", turn_index)


def handle_unclear(agent: str, patient: str, turn_index: int) -> BotDecision:
    if contains_any(agent, "appointment", "medication", "insurance", "something else", "what do you mean", "tell me more"):
        if "rescheduling my follow-up" not in patient:
            return BotDecision("I think it was about rescheduling my follow-up appointment from last time.", False, "clarified vague request")
        return BotDecision("I need to move that follow-up to another weekday afternoon.", False, "follow-up details")
    if asks_how_help(agent):
        return BotDecision("Hi, I need to fix my thing from last time.", False, "vague opening")
    return close_or_repeat("I mean I need help rescheduling my follow-up appointment from last time.", turn_index)


def handle_interruption(agent: str, patient: str, turn_index: int) -> BotDecision:
    if contains_any(agent, "urgent", "pain", "injury", "routine"):
        return BotDecision("It is routine, not urgent. Sorry to interrupt, I only have a minute, and I need any weekday after 4 PM this week.", False, "routine with interruption")
    if contains_any(agent, "when", "date", "time", "availability"):
        return BotDecision("Any weekday after 4 PM this week works for me.", False, "availability")
    if asks_how_help(agent) or contains_any(agent, "appointment"):
        if "only have a minute" not in patient:
            return BotDecision("I need a same-week appointment. Sorry to interrupt, but I only have a minute.", False, "same week request")
        return BotDecision("I need a same-week routine appointment, any weekday after 4 PM.", False, "repeat request")
    if contains_any(agent, "confirm", "scheduled", "booked"):
        return BotDecision("That works. Thank you, goodbye.", True, "confirmed")
    return close_or_repeat("I need a same-week routine appointment, any weekday after 4 PM.", turn_index)


# ------------------------------ helper methods ------------------------------


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
        "11_after_hours_confusion": "Hi, I saw a lab result in the portal and want to know if a doctor can explain it tonight.",
        "12_spanish_language": "Hi, do you have Spanish support? I prefer Spanish.",
    }.get(scenario_id, "Hi, I need help with an appointment.")


def scenario_request(scenario_id: str) -> str:
    return {
        "01_simple_schedule": "I would like to schedule a new patient annual checkup.",
        "02_reschedule": "I need to reschedule my Friday 3 PM appointment to Monday after 2 PM.",
        "03_cancel": "I need to cancel my appointment and I do not want to reschedule today.",
        "04_refill_normal": "I need a refill for lisinopril 10 milligrams, once daily, sent to CVS on Main Street.",
        "05_refill_urgent_symptom": "I need an albuterol refill and I felt mildly short of breath after walking upstairs.",
        "06_office_hours_weekend": "I wanted to know if Sunday at 10 AM is available for a checkup.",
        "07_insurance_question": "I want to know if you accept Aetna and whether I need a referral for an orthopedic visit.",
        "08_location_question": "I want to know which location has parking and wheelchair access before scheduling.",
        "09_unclear_request": "I need help rescheduling my follow-up appointment from last time.",
        "10_interruption_barge_in": "I need a same-week routine appointment, any weekday after 4 PM.",
    }.get(scenario_id, "I need help with an appointment.")


def close_or_repeat(reply: str, turn_index: int) -> BotDecision:
    if turn_index >= 6:
        return BotDecision("Thank you, that helps. Goodbye.", True, "closing after enough turns")
    return BotDecision(reply, False, "repeat scenario request")


def last_text(transcript: list[dict[str, Any]], speaker: str) -> str:
    for row in reversed(transcript):
        if row.get("speaker") == speaker:
            return str(row.get("text", ""))
    return ""


def normalize(text: str) -> str:
    return clean_text(text).lower()


def contains_any(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def asks_if_speaking_to_jamie(text: str) -> bool:
    return contains_any(text, "speaking with jamie", "am i speaking with jamie", "is this jamie", "with jamie", "janie")


def asks_name(text: str) -> bool:
    return contains_any(text, "first and last name", "full name", "your name", "tell me your name")


def asks_dob(text: str) -> bool:
    return contains_any(text, "date of birth", "day of birth", "dob", "birthday", "birth before", "jane of birth", "birth")


def asks_phone(text: str) -> bool:
    return contains_any(text, "phone", "callback", "call back number", "best number")


def asks_how_help(text: str) -> bool:
    return contains_any(text, "how can i help", "how may i help", "what can i help", "what would you like", "how can i assist", "something else")


def asks_appointment_type(text: str) -> bool:
    return contains_any(text, "type of appointment", "what type of appointment", "new patient", "follow-up", "routine")


def no_clear_speech(text: str) -> bool:
    return "no clear speech" in text or "no speech" in text


def count_mentions(text: str, needle: str) -> int:
    return text.count(needle)


# The functions below are still used by analyze/debug utilities and tests from the
# first version of the repo, so they remain as compatible helpers.

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
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 420:
        text = text[:417].rsplit(" ", 1)[0] + "..."
    return text
