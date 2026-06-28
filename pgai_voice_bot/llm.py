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
    """Scenario-aware patient responder for live assessment calls.

    This version is deterministic on purpose. The earlier attempts were more
    flexible, but they sometimes repeated the same detail or ended the call
    before accepting/declining an offered option. For this challenge, coherent
    voice interaction is the first evaluation gate, so the live caller should be
    predictable, short, and patient-like.

    The responder reads only the latest agent turn plus the patient history, then
    chooses a concise patient response that advances the scenario. OpenAI is
    still useful for offline bug analysis, but the live call no longer depends on
    an LLM call at each turn.
    """

    def __init__(self) -> None:
        self.settings = get_settings(require_twilio=False)

    def next_reply(self, scenario: Scenario, transcript: list[dict[str, Any]], turn_index: int) -> BotDecision:
        last_agent = last_text(transcript, "agent")
        agent = normalize(last_agent)
        patient_history = "\n".join(row.get("text", "") for row in transcript if row.get("speaker") == "patient")
        patient = normalize(patient_history)

        if not patient_history.strip() or turn_index == 0:
            return BotDecision(first_request(scenario.id), False, "first request")

        # Identity checks are handled before scenario logic so the bot sounds like
        # a real patient completing intake.
        if asks_if_speaking_to_jamie(agent):
            return self._dedupe("Yes, this is Jamie Lee.", False, "identity confirmation", patient, turn_index)

        if asks_name(agent):
            return self._dedupe("My name is Jamie Lee.", False, "name provided", patient, turn_index)

        if asks_dob(agent):
            if count_mentions(patient, "july 4") >= 1:
                return self._dedupe(f"It is {DEMO_DOB}.", False, "dob repeated once", patient, turn_index)
            return BotDecision(f"Sure, my date of birth is {DEMO_DOB}.", False, "dob provided")

        if asks_phone(agent):
            return self._dedupe(f"The best callback number is {DEMO_PHONE}.", False, "phone provided", patient, turn_index)

        if no_clear_speech(agent):
            # Repeat once if Twilio/agent did not hear clearly. After that, close
            # gracefully instead of creating a loop.
            return self._dedupe(scenario_request(scenario.id), False, "agent did not hear clearly", patient, turn_index)

        handler = {
            "01_simple_schedule": handle_simple_schedule,
            "02_reschedule": handle_reschedule,
            "03_cancel": handle_cancel,
            "04_refill_normal": handle_refill_normal,
            "05_refill_urgent_symptom": handle_refill_urgent,
            "06_office_hours_weekend": handle_weekend_hours,
            "07_insurance_question": handle_insurance,
            "08_location_question": handle_location,
            "09_unclear_request": handle_unclear,
            "10_interruption_barge_in": handle_interruption,
        }.get(scenario.id)

        if handler:
            decision = handler(agent, patient, turn_index)
            return self._dedupe(decision.reply, decision.done, decision.notes, patient, turn_index)

        if turn_index >= 6:
            return BotDecision("Thank you, goodbye.", True, "max turns")
        return self._dedupe(scenario_request(scenario.id), False, "default scenario request", patient, turn_index)

    def _dedupe(self, reply: str, done: bool, notes: str, patient: str, turn_index: int) -> BotDecision:
        """Avoid saying the exact same sentence over and over.

        One repeat is acceptable in a noisy voice call. More than that sounds
        broken, so the caller exits politely and marks the call complete.
        """
        reply_norm = normalize(reply)
        repeats = count_exact_patient_reply(patient, reply_norm)
        if not done and repeats >= 1 and turn_index >= 4:
            return BotDecision(
                "I think I already gave the details. Thank you for checking; I will follow up with the office. Goodbye.",
                True,
                f"stopped repeated reply: {notes}",
            )
        return BotDecision(reply, done, notes)


# ----------------------------- scenario handlers -----------------------------


def handle_simple_schedule(agent: str, patient: str, turn_index: int) -> BotDecision:
    if offers_specific_slot(agent):
        return BotDecision("Yes, please book that slot.", False, "accept offered appointment")
    if contains_any(agent, "is that right", "is that correct", "just to confirm"):
        return BotDecision("Yes, that is correct.", False, "confirm appointment type")
    if contains_any(agent, "specific provider", "provider", "doctor", "first available"):
        return BotDecision("I am open to the first available provider.", False, "provider preference")
    if contains_any(agent, "urgent", "pain", "injury", "emergency"):
        return BotDecision("It is not urgent. It is just a routine annual checkup.", False, "non urgent")
    if contains_any(agent, "when", "date", "time", "availability", "prefer"):
        return BotDecision("Next Tuesday or Wednesday morning would be best if either is available.", False, "availability")
    if contains_any(agent, "scheduled", "booked", "confirmed", "you are all set"):
        return BotDecision("Great, thank you. Goodbye.", True, "appointment confirmed")
    if asks_how_help(agent) or asks_appointment_type(agent) or contains_any(agent, "what type", "what brings you"):
        return BotDecision("I would like to schedule a new patient annual checkup.", False, "appointment type")
    return close_or_repeat("I would like to schedule a new patient annual checkup, preferably next Tuesday or Wednesday morning.", turn_index)


def handle_reschedule(agent: str, patient: str, turn_index: int) -> BotDecision:
    if contains_any(agent, "document your request", "follow up with you", "support team", "clinic support"):
        return BotDecision("Yes, please document that I want to move the Friday 3 PM appointment to Monday after 2 PM. Thank you.", True, "accept support follow up")
    if contains_any(agent, "no appointment", "no appointments", "don't see", "do not see", "don't have", "do not have", "not on file", "unable to proceed"):
        return BotDecision("That's strange. I was told I had a Friday 3 PM appointment. Could you document a follow-up for the office to review it?", False, "appointment not found")
    if contains_any(agent, "book a new", "schedule a new", "new appointment instead"):
        return BotDecision("No thank you. I only want to reschedule the existing Friday 3 PM appointment.", False, "reject new appointment")
    if contains_any(agent, "current", "existing", "which appointment", "what appointment", "what time"):
        return BotDecision("It is my Friday 3 PM appointment with Dr. Patel.", False, "current appointment")
    if contains_any(agent, "when", "date", "time", "availability", "move"):
        return BotDecision("I need to move it to the following Monday after 2 PM.", False, "new time")
    if contains_any(agent, "rescheduled", "changed", "all set"):
        return BotDecision("Thank you, that works. Goodbye.", True, "rescheduled")
    if asks_how_help(agent):
        return BotDecision("I need to reschedule my Friday 3 PM appointment because of a work conflict.", False, "reschedule request")
    return close_or_repeat("I need to reschedule my Friday 3 PM appointment to the following Monday after 2 PM.", turn_index)


def handle_cancel(agent: str, patient: str, turn_index: int) -> BotDecision:
    if contains_any(agent, "connect you", "representative", "patient support", "can't complete", "cannot complete"):
        return BotDecision("Okay, please connect me with patient support. I still do not want to reschedule today. Thank you.", True, "support handoff accepted")
    if contains_any(agent, "new appointment", "book", "reschedule", "schedule") and contains_any(agent, "would you like", "instead", "right now", "today"):
        return BotDecision("No thank you. I only want to cancel it today, not reschedule.", False, "decline reschedule")
    if contains_any(agent, "no appointment", "no appointments", "don't have", "do not have", "not scheduled"):
        return BotDecision("Okay, thank you for checking. I will follow up with the office if needed. Goodbye.", True, "no appointment")
    if contains_any(agent, "cancelled", "canceled", "cancel it", "cancel that", "all set"):
        return BotDecision("Thank you for confirming. Goodbye.", True, "cancel confirmed")
    if asks_how_help(agent) or contains_any(agent, "what would you like"):
        return BotDecision("I need to cancel my dermatology appointment for next Thursday at 9 AM, and I do not want to reschedule today.", False, "cancel request")
    return close_or_repeat("Please cancel my dermatology appointment for next Thursday at 9 AM. I do not want to reschedule today.", turn_index)


def handle_refill_normal(agent: str, patient: str, turn_index: int) -> BotDecision:
    if contains_any(agent, "how many days", "days of", "are you out", "already out", "left"):
        return BotDecision("I have two pills left.", False, "days remaining")
    if contains_any(agent, "would you like to continue", "continue with your", "process your request"):
        return BotDecision("Yes, please continue with the refill request.", False, "continue refill")
    if contains_any(agent, "pharmacy"):
        return BotDecision("Please send it to CVS on Main Street.", False, "pharmacy")
    if contains_any(agent, "dosage", "dose", "what medication", "which medication", "medication"):
        return BotDecision("It is lisinopril 10 milligrams, once daily.", False, "medication details")
    if contains_any(agent, "symptom", "urgent", "side effect", "emergency"):
        return BotDecision("No symptoms. This is just a routine refill.", False, "no symptoms")
    if contains_any(agent, "1 to 2 business days", "one to two business days", "24", "48", "processed within"):
        return BotDecision("Great. Please submit the refill request. Thank you, goodbye.", True, "timing answered")
    if contains_any(agent, "sent", "submitted", "requested", "provider", "all set"):
        return BotDecision("Thank you, goodbye.", True, "refill complete")
    if asks_how_help(agent) or contains_any(agent, "refill", "prescription"):
        if "lisinopril" not in patient:
            return BotDecision("I need a refill for lisinopril 10 milligrams. I have two pills left, and I use CVS on Main Street.", False, "refill request")
        return BotDecision("I also wanted to ask how long refills usually take.", False, "timing question")
    return close_or_repeat("I need a refill for lisinopril 10 milligrams, once daily, sent to CVS on Main Street.", turn_index)


def handle_refill_urgent(agent: str, patient: str, turn_index: int) -> BotDecision:
    if contains_any(agent, "how many days", "days of", "are you out", "already out", "left"):
        return BotDecision("I have about one or two doses left.", False, "inhaler remaining")
    if contains_any(agent, "chest pain", "severe", "911", "emergency", "urgent care", "worse"):
        return BotDecision("Understood. If it gets severe or I have chest pain, I will seek urgent care or call 911. Please also send the refill request.", True, "safe escalation acknowledged")
    if contains_any(agent, "appointment", "provider", "discuss", "schedule", "speak with"):
        return BotDecision("Yes, I can speak with a provider. Should I seek urgent care if the breathing gets worse before then?", False, "asks escalation guidance")
    if asks_how_help(agent) or contains_any(agent, "refill", "medication", "inhaler"):
        return BotDecision("I need a refill for my albuterol inhaler. I also felt mildly short of breath after walking upstairs today.", False, "refill with symptom")
    return close_or_repeat("I need an albuterol refill, and I had mild shortness of breath after walking upstairs.", turn_index)


def handle_weekend_hours(agent: str, patient: str, turn_index: int) -> BotDecision:
    if contains_any(agent, "is that correct", "is that right", "just to confirm", "general checkup", "routine office"):
        return BotDecision("Yes, that is correct.", False, "confirm checkup")
    if contains_any(agent, "closed", "not open", "sunday"):
        return BotDecision("Okay, if Sunday is not available, Monday or Tuesday morning works for me.", False, "accept weekday")
    if contains_any(agent, "preferred day", "preferred time", "what day", "what time"):
        return BotDecision("Monday or Tuesday morning would work.", False, "weekday preference")
    if contains_any(agent, "scheduled", "booked", "confirmed", "all set"):
        return BotDecision("Thank you. Goodbye.", True, "confirmed")
    if contains_any(agent, "when", "date", "time", "availability"):
        return BotDecision("I was hoping for Sunday at 10 AM. If the office is closed then, I can do Monday or Tuesday morning.", False, "weekend request")
    if asks_how_help(agent) or contains_any(agent, "what would you like"):
        return BotDecision("Can I come in Sunday at 10 AM for a checkup?", False, "sunday request")
    return close_or_repeat("I wanted to check if Sunday at 10 AM is available for a checkup.", turn_index)


def handle_insurance(agent: str, patient: str, turn_index: int) -> BotDecision:
    if ("confirm with your insurance" in agent or "check with your insurance" in agent or "check with your insurance plan" in agent or "good idea" in agent) and "aetna" in patient:
        return BotDecision("That answers my question. Thank you, goodbye.", True, "insurance answered")
    if contains_any(agent, "which type", "what type", "reason for the referral", "specialist"):
        return BotDecision("It would be for an orthopedic visit for knee pain. I mainly want to know if Aetna is accepted and if a referral is required.", False, "specialist type")
    if contains_any(agent, "anything else"):
        return BotDecision("No, that answers my question. Thank you, goodbye.", True, "complete")
    if asks_how_help(agent) or contains_any(agent, "insurance", "aetna", "referral"):
        if "aetna" not in patient:
            return BotDecision("Do you accept Aetna, and would I need a referral for an orthopedic specialist visit?", False, "insurance question")
        return BotDecision("Thanks. To be safe, should I also confirm the referral requirement with my insurance plan?", False, "verification question")
    return close_or_repeat("I am calling to ask if you accept Aetna and whether I need a referral for an orthopedic specialist visit.", turn_index)


def handle_location(agent: str, patient: str, turn_index: int) -> BotDecision:
    agent_has_location_answer = contains_any(agent, "address", "parking", "wheelchair", "accessible", "location", "athens", "nashville", "suite")
    if agent_has_location_answer and contains_any(agent, "would you like to schedule", "would you like to book"):
        return BotDecision("Not yet. I just needed the parking and wheelchair access information. Thank you, goodbye.", True, "decline scheduling")
    if agent_has_location_answer and ("repeat the address" not in patient and "write it down" not in patient):
        return BotDecision("Thank you. Could you repeat the address once slowly so I can write it down?", False, "ask repeat")
    if agent_has_location_answer:
        return BotDecision("Got it. Thank you, goodbye.", True, "location complete")
    if asks_how_help(agent) or contains_any(agent, "appointment", "something else", "what would you like"):
        return BotDecision("Before I schedule, I want to know which location has parking and wheelchair access.", False, "location question")
    return close_or_repeat("I am trying to find the office location with parking and wheelchair access before scheduling.", turn_index)


def handle_unclear(agent: str, patient: str, turn_index: int) -> BotDecision:
    if contains_any(agent, "no upcoming", "don't have", "do not have", "not on file", "there isn't"):
        return BotDecision("Okay, I understand. I was trying to move a follow-up, but if there is nothing on file I will call back later. Thank you.", True, "no follow-up found")
    if contains_any(agent, "book a new", "schedule a new", "new weekday"):
        return BotDecision("No, I was trying to move an existing follow-up, not book a new one. Thank you for checking.", True, "decline new follow-up")
    if contains_any(agent, "appointment", "medication", "insurance", "something else", "what do you mean", "tell me more", "past appointment"):
        if "follow-up appointment" not in patient:
            return BotDecision("I think it was about rescheduling my follow-up appointment from last time.", False, "clarified vague request")
        return BotDecision("I need to move that follow-up to another weekday afternoon.", False, "follow-up details")
    if asks_how_help(agent):
        return BotDecision("Hi, I need to fix my thing from last time.", False, "vague opening")
    return close_or_repeat("I mean I need help rescheduling my follow-up appointment from last time.", turn_index)


def handle_interruption(agent: str, patient: str, turn_index: int) -> BotDecision:
    if contains_any(agent, "no routine", "no openings", "no appointments", "none available"):
        return BotDecision("Okay. What is the latest routine appointment available next week?", False, "asks next week alternative")
    if offers_specific_slot(agent):
        if contains_any(agent, "4:", "after 4", "4 pm", "4:00", "5:", "evening"):
            return BotDecision("Yes, that works. Please book it.", False, "accept after four slot")
        return BotDecision("That is a little too early for me. I need after 4 PM, but thank you for checking. Goodbye.", True, "decline early slot")
    if contains_any(agent, "open to anyone", "anyone available", "any provider", "first available"):
        return BotDecision("Yes, I am open to any available provider.", False, "provider flexible")
    if contains_any(agent, "urgent", "pain", "injury", "routine"):
        return BotDecision("It is routine, not urgent. I only have a minute, and I need any weekday after 4 PM this week.", False, "routine with time constraint")
    if contains_any(agent, "when", "date", "time", "availability"):
        return BotDecision("Any weekday after 4 PM this week works for me.", False, "availability")
    if contains_any(agent, "scheduled", "booked", "confirmed", "all set"):
        return BotDecision("That works. Thank you, goodbye.", True, "confirmed")
    if asks_how_help(agent) or contains_any(agent, "appointment"):
        if "only have a minute" not in patient:
            return BotDecision("I need a same-week appointment. Sorry to interrupt, but I only have a minute.", False, "same week request")
        return BotDecision("I need a same-week routine appointment, any weekday after 4 PM.", False, "repeat request")
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
    if turn_index >= 7:
        return BotDecision("Thank you for checking. Goodbye.", True, "closing after enough turns")
    return BotDecision(reply, False, "scenario request")


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
    return contains_any(text, "speaking with jamie", "am i speaking with jamie", "is this jamie", "with jamie", "janie", "jamie?")


def asks_name(text: str) -> bool:
    return contains_any(text, "first and last name", "full name", "your name", "tell me your name")


def asks_dob(text: str) -> bool:
    return contains_any(text, "date of birth", "day of birth", "dob", "birthday", "birth before", "jane of birth", "birth")


def asks_phone(text: str) -> bool:
    return contains_any(text, "phone", "callback", "call back number", "best number")


def asks_how_help(text: str) -> bool:
    return contains_any(text, "how can i help", "how may i help", "what can i help", "what would you like", "how can i assist", "something else")


def asks_appointment_type(text: str) -> bool:
    return contains_any(text, "type of appointment", "what type of appointment", "new patient", "follow-up", "routine office", "routine visit")


def no_clear_speech(text: str) -> bool:
    return "no clear speech" in text or "no speech" in text


def offers_specific_slot(text: str) -> bool:
    return (
        contains_any(text, "opening", "available", "slot", "appointment")
        and contains_any(text, "would you like", "does that work", "can book", "book that", "schedule that", "latest slot", "at ")
    )


def count_mentions(text: str, needle: str) -> int:
    return text.count(needle)


def count_exact_patient_reply(patient_history_norm: str, reply_norm: str) -> int:
    # Patient turns are joined with newlines before normalization. This check is
    # intentionally simple and conservative.
    return patient_history_norm.count(reply_norm)


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
