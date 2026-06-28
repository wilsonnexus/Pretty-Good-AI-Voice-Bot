from __future__ import annotations

import json
import os
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
    """Hybrid patient responder for live assessment calls.

    The first versions were either too scripted or too deterministic. This version
    keeps fast rules for identity, DOB, and obvious form fields, then uses the
    OpenAI API for the conversational parts when OPENAI_API_KEY is available.
    That makes the caller adapt to the agent's actual wording while still keeping
    the conversation bounded, polite, and safe.
    """

    def __init__(self) -> None:
        self.settings = get_settings(require_twilio=False)
        self._client = None
        self.live_llm_enabled = os.getenv("LIVE_LLM_RESPONDER", "true").strip().lower() not in {
            "0",
            "false",
            "no",
        }
        if self.settings.openai_api_key and self.live_llm_enabled:
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=self.settings.openai_api_key)
            except Exception:
                self._client = None

    def next_reply(self, scenario: Scenario, transcript: list[dict[str, Any]], turn_index: int) -> BotDecision:
        last_agent = last_text(transcript, "agent")
        agent = normalize(last_agent)
        patient_turns = [str(row.get("text", "")) for row in transcript if row.get("speaker") == "patient"]
        patient_history = "\n".join(patient_turns)
        patient = normalize(patient_history)

        # On the first turn, answer the agent's greeting if it already contains a
        # question. Otherwise start with the scenario request.
        if not patient_history.strip() or turn_index == 0:
            initial = first_turn_reply(scenario.id, agent)
            return BotDecision(initial, False, "first turn")

        # Universal intake questions. Keep these before LLM calls for speed and
        # reliability, but do not let them steal pharmacy prompts.
        quick = self._universal_reply(agent, patient, scenario.id)
        if quick is not None:
            return self._finalize(quick, patient, turn_index)

        # Deterministic high-confidence scenario logic for common voice-agent
        # workflow branches.
        scripted = scenario_rule_reply(scenario.id, agent, patient, turn_index)
        if scripted is not None:
            return self._finalize(scripted, patient, turn_index)

        # Dynamic responder for the cases where a rigid if/else tree becomes
        # brittle: appointment alternatives, agent contradictions, clarifying
        # questions, and partial handoffs.
        if self._client is not None:
            dynamic = self._openai_reply(scenario, transcript, turn_index)
            return self._finalize(dynamic, patient, turn_index)

        fallback = safe_fallback(scenario.id, agent, patient, turn_index)
        return self._finalize(fallback, patient, turn_index)

    def _universal_reply(self, agent: str, patient: str, scenario_id: str) -> BotDecision | None:
        if asks_identity(agent):
            # If the agent combines identity with the first greeting, answer the
            # identity and briefly state the purpose so the call moves naturally.
            if not has_said_identity(patient):
                purpose = first_request_without_hi(scenario_id)
                return BotDecision(f"Yes, this is Jamie Lee. {purpose}", False, "identity plus purpose")
            return BotDecision("Yes, this is Jamie Lee.", False, "identity confirmation")

        if asks_name(agent):
            return BotDecision("My name is Jamie Lee.", False, "name provided")

        if asks_dob(agent):
            return BotDecision(f"Sure, my date of birth is {DEMO_DOB}.", False, "dob provided")

        # Callback number confirmation should not fire on pharmacy prompts that
        # merely mention a pharmacy phone/fax number.
        if asks_callback_number(agent) and not asks_pharmacy(agent):
            if contains_any(agent, "is that correct", "is that right", "correct for a call", "best number"):
                return BotDecision("Yes, that is the best callback number.", False, "callback confirmed")
            return BotDecision(f"The best callback number is {DEMO_PHONE}.", False, "callback provided")

        return None

    def _openai_reply(self, scenario: Scenario, transcript: list[dict[str, Any]], turn_index: int) -> BotDecision:
        profile = scenario_profile(scenario.id)
        transcript_text = render_transcript_for_prompt(transcript)
        last_patient = last_text(transcript, "patient")
        last_agent = last_text(transcript, "agent")

        instructions = f"""
You are the patient in a live phone call with a healthcare voice agent.
Your job is to sound like a real, polite patient while testing the agent.

Universal identity for this demo account:
- Name: {DEMO_NAME}
- Date of birth: {DEMO_DOB}
- Callback phone: use the number the agent has on file if it offers one; otherwise use {DEMO_PHONE}

Scenario:
{profile}

Rules for the next spoken reply:
- Reply ONLY as the patient.
- Answer the agent's latest question directly before adding anything else.
- Use one short natural sentence when possible; two short sentences max.
- Do not repeat the exact previous patient reply.
- Do not sound annoyed, robotic, or scripted.
- Do not say: "my goal", "scenario", "test", "bot", "benchmark", or "I already gave".
- If the agent offers a reasonable alternative, accept it or ask for one specific alternative.
- If the agent offers something that violates the patient's constraint, politely ask for the closest acceptable option.
- Only say goodbye when the question is answered, the request is completed, or the agent clearly cannot help further.
- If you say goodbye, set done true. Otherwise set done false.
- Never invent real patient data beyond the demo identity and scenario details.

Return strict JSON: {{"reply":"...","done":false,"notes":"..."}}
""".strip()

        user_input = f"""
Turn index: {turn_index}
Latest agent text: {last_agent}
Previous patient reply: {last_patient}

Transcript so far:
{transcript_text}

Choose the next patient reply.
""".strip()
        try:
            response = self._client.responses.create(
                model=self.settings.openai_model,
                instructions=instructions,
                input=user_input,
                temperature=0.25,
                max_output_tokens=140,
            )
            raw = getattr(response, "output_text", "") or ""
            parsed = parse_json_loose(raw)
            reply = clean_for_speech(str(parsed.get("reply", "")))
            done = bool(parsed.get("done", False))
            notes = str(parsed.get("notes", ""))[:500]
            if not reply:
                raise ValueError(f"empty model reply: {raw!r}")
            return BotDecision(reply=reply, done=done, notes=f"dynamic: {notes}")
        except Exception as exc:
            fallback = safe_fallback(scenario.id, normalize(last_agent), normalize(render_patient_text(transcript)), turn_index)
            return BotDecision(fallback.reply, fallback.done, f"dynamic fallback: {exc}")

    def _finalize(self, decision: BotDecision, patient: str, turn_index: int) -> BotDecision:
        reply = clean_for_speech(decision.reply)
        done = bool(decision.done)
        notes = decision.notes

        forbidden = ["my goal", "scenario", "benchmark", "patient bot", "voice bot", "test line", "i already gave"]
        if any(term in normalize(reply) for term in forbidden):
            reply = "Thanks for your help. I will follow up with the office if needed. Goodbye."
            done = True
            notes = f"sanitized forbidden wording: {notes}"

        # Avoid exact repetition, but do not hang up rudely. Ask for the next step
        # or choose a polite close depending on how far into the call we are.
        if count_exact_patient_reply(patient, normalize(reply)) >= 1 and not done:
            if turn_index >= 7:
                reply = "Thank you for checking. I will follow up with the office if needed. Goodbye."
                done = True
                notes = f"polite close after repeated reply: {notes}"
            else:
                reply = "Okay, what would be the next best option?"
                done = False
                notes = f"rephrased repeated reply: {notes}"

        if done and "goodbye" not in normalize(reply):
            reply = reply.rstrip(".") + ". Thank you, goodbye."

        if turn_index >= 9 and not done:
            reply = "Thank you for your help. I will follow up with the office if needed. Goodbye."
            done = True
            notes = f"max turn polite close: {notes}"

        return BotDecision(reply=reply, done=done, notes=notes)


# ----------------------------- deterministic rules -----------------------------


def scenario_rule_reply(scenario_id: str, agent: str, patient: str, turn_index: int) -> BotDecision | None:
    if scenario_id == "01_simple_schedule":
        return rule_simple_schedule(agent, patient)
    if scenario_id == "02_reschedule":
        return rule_reschedule(agent, patient)
    if scenario_id == "03_cancel":
        return rule_cancel(agent, patient)
    if scenario_id == "04_refill_normal":
        return rule_refill_normal(agent, patient)
    if scenario_id == "05_refill_urgent_symptom":
        return rule_refill_urgent(agent, patient)
    if scenario_id == "06_office_hours_weekend":
        return rule_weekend(agent, patient)
    if scenario_id == "07_insurance_question":
        return rule_insurance(agent, patient)
    if scenario_id == "08_location_question":
        return rule_location(agent, patient)
    if scenario_id == "09_unclear_request":
        return rule_unclear(agent, patient)
    if scenario_id == "10_interruption_barge_in":
        return rule_interruption(agent, patient)
    return None


def rule_simple_schedule(agent: str, patient: str) -> BotDecision | None:
    if contains_any(agent, "already have", "already scheduled", "already have a new patient", "can't schedule another", "unable to book another"):
        return BotDecision("Oh, I understand. Please keep my current appointment as it is. Thank you, goodbye.", True, "already scheduled")
    if confirmed_or_set(agent):
        return BotDecision("Great, thank you for confirming. Goodbye.", True, "appointment confirmed")
    if asks_confirmation(agent):
        return BotDecision("Yes, that is correct.", False, "confirm schedule details")
    if asks_provider(agent):
        return BotDecision("I am open to the first available provider.", False, "provider preference")
    if asks_preferred_time(agent):
        return BotDecision("Next Tuesday or Wednesday morning would be best if either is available.", False, "time preference")
    if offers_real_slot(agent):
        return BotDecision("Yes, that works. Please book that appointment.", False, "accept offered slot")
    if asks_how_help(agent) or asks_appointment_type(agent):
        return BotDecision("I would like to schedule a new patient annual checkup.", False, "appointment type")
    return None


def rule_reschedule(agent: str, patient: str) -> BotDecision | None:
    if contains_any(agent, "is this the appointment", "is this the one"):
        return BotDecision("Yes, that is the appointment I need to move.", False, "confirm appointment to reschedule")
    if contains_any(agent, "no openings on monday", "no openings", "no available", "no appointments"):
        return BotDecision("Okay, could we try the closest weekday afternoon after 2 PM, or connect me to the clinic if none are available?", False, "asks alternative")
    if contains_any(agent, "would any of these", "do any of these", "would that work") and offers_real_slot(agent):
        return BotDecision("The latest afternoon option works for me if Monday after 2 PM is not available.", False, "accept backup slot")
    if contains_any(agent, "document", "add a note", "follow up", "clinic support", "connect you to the clinic"):
        return BotDecision("Yes, please document the request and have the clinic follow up with me. Thank you.", True, "accept follow up")
    if confirmed_or_set(agent) or contains_any(agent, "rescheduled", "changed"):
        return BotDecision("Thank you for confirming the change. Goodbye.", True, "reschedule confirmed")
    if asks_preferred_time(agent) or contains_any(agent, "when would", "what time", "what day"):
        return BotDecision("The following Monday after 2 PM would be best.", False, "preferred reschedule time")
    if asks_how_help(agent):
        return BotDecision("I need to reschedule my appointment because of a work conflict.", False, "reschedule request")
    return None


def rule_cancel(agent: str, patient: str) -> BotDecision | None:
    if contains_any(agent, "reason for cancelling", "reason for canceling", "reason for the cancellation", "can you share the reason"):
        return BotDecision("I have a work conflict and cannot make that appointment.", False, "cancel reason")
    if contains_any(agent, "is this the appointment", "is that correct", "confirm", "referring to this appointment"):
        return BotDecision("Yes, please cancel that appointment, and I do not want to reschedule today.", False, "confirm cancel")
    if contains_any(agent, "not see", "only see", "do not see", "don't see"):
        return BotDecision("If that appointment is not showing, please do not cancel anything today. I will follow up with the office. Thank you, goodbye.", True, "avoid wrong cancel")
    if contains_any(agent, "cancelled", "canceled", "cancelled your", "canceled your", "all set"):
        return BotDecision("Thank you for confirming. Goodbye.", True, "cancel complete")
    if contains_any(agent, "reschedule", "new appointment") and contains_any(agent, "would you like", "do you want"):
        return BotDecision("No thank you. I only want to cancel today, not reschedule.", False, "decline reschedule")
    if asks_how_help(agent):
        return BotDecision("I need to cancel my appointment, and I do not want to reschedule today.", False, "cancel request")
    return None


def rule_refill_normal(agent: str, patient: str) -> BotDecision | None:
    if asks_pharmacy(agent):
        return BotDecision("Please send it to CVS on Main Street.", False, "pharmacy")
    if contains_any(agent, "is that correct", "just to confirm", "to confirm") and contains_any(agent, "lisinopril", "lucida", "luna", "refill", "10"):
        return BotDecision("Yes, that is correct: lisinopril 10 milligrams once daily.", False, "confirm medication")
    if asks_days_left(agent):
        return BotDecision("I have two pills left.", False, "days remaining")
    if asks_symptoms_or_urgency(agent):
        return BotDecision("No symptoms or urgency. This is just a routine refill.", False, "no symptoms")
    if asks_callback_number(agent):
        return BotDecision("Yes, that is the best callback number.", False, "callback confirmed")
    if contains_any(agent, "how long", "1 to 2 business", "one to two business", "processed"):
        return BotDecision("That works. Please submit the refill request. Thank you, goodbye.", True, "refill timing accepted")
    if confirmed_or_set(agent) or contains_any(agent, "submitted", "sent to", "request has been sent", "request is in"):
        return BotDecision("Thank you for submitting it. Goodbye.", True, "refill submitted")
    if asks_how_help(agent) or contains_any(agent, "refill", "prescription"):
        return BotDecision("I need a refill for lisinopril 10 milligrams, once daily, sent to CVS on Main Street.", False, "refill request")
    return None


def rule_refill_urgent(agent: str, patient: str) -> BotDecision | None:
    if asks_pharmacy(agent):
        return BotDecision("Please send it to Walgreens on Pine Street.", False, "pharmacy")
    if contains_any(agent, "is that correct", "just to confirm", "to confirm") and contains_any(agent, "albuterol", "inhaler", "refill"):
        return BotDecision("Yes, that is correct. I need the albuterol refill, and I had mild shortness of breath after stairs today.", False, "confirm urgent refill")
    if asks_days_left(agent):
        return BotDecision("I have about one or two doses left.", False, "doses remaining")
    if asks_symptoms_or_urgency(agent):
        return BotDecision("I had mild shortness of breath after walking upstairs today, but no chest pain and it is not severe right now.", False, "symptom details")
    if asks_callback_number(agent):
        return BotDecision("Yes, that is the best callback number.", False, "callback confirmed")
    if contains_any(agent, "911", "emergency", "urgent care", "worsening", "chest pain", "severe"):
        return BotDecision("Understood. If it becomes severe or I have chest pain, I will seek urgent care or call 911. Thank you, goodbye.", True, "safety guidance acknowledged")
    if contains_any(agent, "provider", "appointment", "speak with", "discuss"):
        return BotDecision("Yes, I can speak with a provider. Should I seek urgent care if the breathing gets worse before then?", False, "asks triage guidance")
    if asks_how_help(agent) or contains_any(agent, "refill", "inhaler", "medication"):
        return BotDecision("I need a refill for my albuterol inhaler. I also felt mildly short of breath after walking upstairs today.", False, "urgent refill request")
    return None


def rule_weekend(agent: str, patient: str) -> BotDecision | None:
    if contains_any(agent, "closed on sundays", "closed on sunday", "not open on sunday", "not open on sundays"):
        return BotDecision("Okay, if Sunday is not available, Monday or Tuesday morning works for me.", False, "accept weekday")
    if contains_any(agent, "no available", "no open", "no appointments") and contains_any(agent, "monday", "tuesday", "morning"):
        return BotDecision("I am flexible. Could you check the next available morning later in the week?", False, "weekday backup")
    if asks_confirmation(agent):
        return BotDecision("Yes, that is correct.", False, "confirm checkup")
    if contains_any(agent, "would you like to schedule", "would you like to book", "can help you book"):
        return BotDecision("Yes, please schedule the next available morning checkup.", False, "schedule weekday")
    if asks_preferred_time(agent):
        return BotDecision("Monday or Tuesday morning would work. If those are full, any weekday morning is okay.", False, "weekday morning preference")
    if confirmed_or_set(agent):
        return BotDecision("Thank you for confirming. Goodbye.", True, "weekend alternate scheduled")
    if asks_how_help(agent):
        return BotDecision("Can I come in Sunday at 10 AM for a checkup? If not, I can do a weekday morning.", False, "weekend request")
    return None


def rule_insurance(agent: str, patient: str) -> BotDecision | None:
    if contains_any(agent, "confirm directly", "confirm with", "check with your insurance", "good idea"):
        return BotDecision("That answers my question. Thank you, goodbye.", True, "insurance answered")
    if contains_any(agent, "check your insurance details", "update them", "update your insurance"):
        return BotDecision("No need to update it right now. I just wanted to know whether I should confirm the referral with Aetna.", False, "decline update")
    if contains_any(agent, "what type", "which type", "reason for the referral", "specialist"):
        return BotDecision("It would be for an orthopedic visit for knee pain.", False, "specialist reason")
    if asks_how_help(agent) or contains_any(agent, "insurance", "aetna", "referral"):
        if "aetna" not in patient:
            return BotDecision("Do you accept Aetna, and would I need a referral for an orthopedic specialist visit?", False, "insurance question")
        return BotDecision("Thanks. To be safe, should I also confirm the referral requirement with my insurance plan?", False, "ask verify")
    return None


def rule_location(agent: str, patient: str) -> BotDecision | None:
    if contains_any(agent, "repeat", "address is") and location_answered(agent):
        return BotDecision("Got it. Thank you, goodbye.", True, "address repeated")
    if location_answered(agent) and not contains_any(patient, "repeat the address", "write it down"):
        return BotDecision("Thank you. Could you repeat the address once slowly so I can write it down?", False, "ask address repeat")
    if location_answered(agent):
        return BotDecision("Got it. Thank you, goodbye.", True, "location complete")
    if asks_how_help(agent) or contains_any(agent, "location", "parking", "wheelchair", "access"):
        return BotDecision("Before I schedule, I want to know which location has parking and wheelchair access.", False, "location question")
    return None


def rule_unclear(agent: str, patient: str) -> BotDecision | None:
    if contains_any(agent, "tell me a bit more", "what do you need to fix", "appointment", "medication", "insurance", "something else"):
        if "follow-up appointment" not in patient:
            return BotDecision("I think it was about rescheduling my follow-up appointment from last time.", False, "clarify vague request")
        return BotDecision("I need to move that follow-up to another weekday afternoon.", False, "follow up details")
    if contains_any(agent, "5:15", "five fifteen"):
        return BotDecision("The 5:15 PM option works for me. Please book that one.", False, "accept latest slot")
    if offers_real_slot(agent) and contains_any(agent, "afternoon", "p.m", "pm"):
        return BotDecision("The latest afternoon time works for me. Please book that one.", False, "accept afternoon")
    if confirmed_or_set(agent):
        return BotDecision("Thank you for helping me fix that. Goodbye.", True, "unclear resolved")
    if contains_any(agent, "no upcoming", "not on file", "do not have", "don't have"):
        return BotDecision("Okay, thanks for checking. I will follow up with the office if needed. Goodbye.", True, "no follow-up")
    if asks_how_help(agent):
        return BotDecision("Hi, I need to fix my thing from last time.", False, "vague opening")
    return None


def rule_interruption(agent: str, patient: str) -> BotDecision | None:
    if contains_any(agent, "text with your appointment", "appointment details"):
        return BotDecision("Yes, please send a text to the number on file. Thank you, goodbye.", True, "text confirmation")
    if confirmed_or_set(agent):
        return BotDecision("That works. Thank you for confirming. Goodbye.", True, "same week scheduled")
    if contains_any(agent, "3 p.m", "3:00", "3:30") and not contains_any(agent, "4:30", "5:", "after 4:30"):
        return BotDecision("Could you check later in the week? I really need 4 PM or later if possible.", False, "decline before four")
    if contains_any(agent, "no open", "no routine", "no appointments", "none available"):
        return BotDecision("Okay, could you check early next week for an appointment after 4 PM?", False, "check next week")
    if asks_confirmation(agent) and contains_any(agent, "routine"):
        return BotDecision("Yes, routine care is correct. I am open to any provider after 4 PM if available.", False, "confirm routine")
    if asks_provider(agent):
        return BotDecision("Yes, I am open to any available provider.", False, "provider flexible")
    if contains_any(agent, "urgent", "pain", "injury"):
        return BotDecision("It is routine, not urgent. I only have a minute, and I need any weekday after 4 PM this week.", False, "routine not urgent")
    if asks_preferred_time(agent):
        return BotDecision("Any weekday after 4 PM this week would be best.", False, "time preference")
    if offers_real_slot(agent):
        if contains_any(agent, "4:30", "5:", "after 4"):
            return BotDecision("Yes, that works. Please book it.", False, "accept after four")
        return BotDecision("That is a little too early for me. Could you check for 4 PM or later?", False, "ask later")
    if asks_how_help(agent):
        return BotDecision("I need a same-week routine appointment. Sorry, I only have a minute, and after 4 PM works best.", False, "same week request")
    return None


# ----------------------------- profiles and fallbacks -----------------------------


def scenario_profile(scenario_id: str) -> str:
    profiles = {
        "01_simple_schedule": "New patient annual checkup. Prefer next Tuesday or Wednesday morning. Open to first available provider. If the agent says an appointment already exists, do not duplicate it; keep the existing booking and close politely.",
        "02_reschedule": "Reschedule an existing appointment because of a work conflict. Prefer the following Monday after 2 PM. If Monday is unavailable, ask for the closest weekday afternoon after 2 PM or accept clinic follow-up.",
        "03_cancel": "Cancel the appointment the agent can see. Do not reschedule. If the agent asks for a reason, say work conflict. If the agent cannot find the intended appointment, do not cancel the wrong one.",
        "04_refill_normal": "Routine lisinopril 10 mg once daily refill. Two pills left. Pharmacy is CVS on Main Street. No symptoms or urgency. Ask how long refill processing usually takes if appropriate.",
        "05_refill_urgent_symptom": "Albuterol inhaler refill. One or two doses left. Pharmacy is Walgreens on Pine Street. Mild shortness of breath after walking upstairs today; no chest pain and not severe. Ask for safety guidance if needed.",
        "06_office_hours_weekend": "Ask for Sunday 10 AM checkup. If Sunday is closed, accept Monday or Tuesday morning. If those are unavailable, accept next available weekday morning.",
        "07_insurance_question": "Ask whether Aetna is accepted and whether a referral is needed for an orthopedic visit for knee pain. Do not update insurance; just ask whether to confirm with the plan.",
        "08_location_question": "Ask which location has parking and wheelchair access before scheduling. Ask the agent to repeat the address once, then close politely.",
        "09_unclear_request": "Start vague: 'I need to fix my thing from last time.' When asked, clarify it means rescheduling a follow-up appointment. Prefer a weekday afternoon and accept the latest afternoon option.",
        "10_interruption_barge_in": "Need a same-week routine appointment, not urgent. Patient is in a hurry but polite. Prefer any weekday after 4 PM. If no after-4 slots this week, ask early next week. Do not accept appointments before 4 PM unless no better option and then close politely.",
    }
    return profiles.get(scenario_id, "Polite patient asking for help with an appointment.")


def safe_fallback(scenario_id: str, agent: str, patient: str, turn_index: int) -> BotDecision:
    if turn_index >= 7:
        return BotDecision("Thank you for your help. I will follow up with the office if needed. Goodbye.", True, "safe max-turn close")
    if asks_confirmation(agent):
        return BotDecision("Yes, that is correct.", False, "fallback confirmation")
    if asks_how_help(agent):
        return BotDecision(first_request_without_hi(scenario_id), False, "fallback purpose")
    if asks_preferred_time(agent):
        return BotDecision("A weekday afternoon would work best for me.", False, "fallback time")
    return BotDecision("Okay, what would be the next best option?", False, "safe fallback")


# ----------------------------- text helpers -----------------------------


def first_turn_reply(scenario_id: str, agent: str) -> str:
    purpose = first_request_without_hi(scenario_id)
    if asks_identity(agent):
        return f"Yes, this is Jamie Lee. {purpose}"
    if asks_dob(agent):
        return f"Sure, my date of birth is {DEMO_DOB}."
    return first_request(scenario_id)


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


def first_request_without_hi(scenario_id: str) -> str:
    text = first_request(scenario_id)
    return re.sub(r"^hi,?\s*", "", text, flags=re.IGNORECASE).strip().capitalize()


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
    for row in transcript[-16:]:
        speaker = row.get("speaker", "unknown").upper()
        text = row.get("text", "")
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def normalize(text: str) -> str:
    return clean_text(text).lower()


def contains_any(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def asks_identity(text: str) -> bool:
    return bool(
        re.search(r"\b(am i|are you|is this|speaking with|with)\s+(jamie|amy|janie|cheney)\b", text)
        or re.search(r"\bare you\s+(jamie|amy|janie|cheney)\b", text)
        or contains_any(text, "may i verify your information, are you jamie")
    )


def has_said_identity(patient: str) -> bool:
    return contains_any(patient, "this is jamie", "jamie lee", "my name is jamie")


def asks_name(text: str) -> bool:
    return contains_any(text, "first and last name", "full name", "your name", "tell me your name")


def asks_dob(text: str) -> bool:
    return contains_any(text, "date of birth", "day of birth", "dob", "birthday", "data birth")


def asks_callback_number(text: str) -> bool:
    return contains_any(text, "callback", "call back", "best number", "number on file", "number is", "correct for a call")


def asks_pharmacy(text: str) -> bool:
    return contains_any(text, "pharmacy", "where you want your medication", "where should", "send it to", "medication sent")


def asks_days_left(text: str) -> bool:
    return contains_any(text, "how many days", "days of", "do you have left", "are you out", "already out", "doses left", "pills left")


def asks_symptoms_or_urgency(text: str) -> bool:
    return contains_any(text, "symptoms", "urgency", "urgent", "anything else", "staff to know", "clinic to know")


def asks_confirmation(text: str) -> bool:
    return contains_any(text, "is that correct", "is that right", "correct?", "to confirm", "just to confirm", "confirm you", "confirm that")


def asks_provider(text: str) -> bool:
    return contains_any(text, "specific provider", "first available", "any available provider", "provider you'd like", "doctor you'd like")


def asks_preferred_time(text: str) -> bool:
    return contains_any(text, "preferred day", "preferred time", "what day", "what time", "time of day", "availability", "when would")


def asks_how_help(text: str) -> bool:
    return contains_any(text, "how can i help", "how may i help", "what can i help", "what would you like", "how can i assist")


def asks_appointment_type(text: str) -> bool:
    return contains_any(text, "type of appointment", "what type of appointment", "new patient", "routine visit", "routine office", "what brings you")


def confirmed_or_set(text: str) -> bool:
    return contains_any(text, "you're all set", "you are all set", "is set", "scheduled", "confirmed", "booked", "appointment is set")


def offers_real_slot(text: str) -> bool:
    has_day_or_time = bool(
        re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text)
        or re.search(r"\b\d{1,2}(:\d{2})?\s*(a\.m\.|p\.m\.|am|pm)\b", text)
    )
    has_offer = contains_any(text, "opening", "openings", "available", "slot", "would any", "would you like", "i have")
    return has_day_or_time and has_offer


def location_answered(text: str) -> bool:
    return contains_any(text, "parking", "wheelchair", "accessible", "address", "athens", "recovery way", "suite", "nashville", "austin")


def count_exact_patient_reply(patient_history_norm: str, reply_norm: str) -> int:
    if not reply_norm:
        return 0
    return patient_history_norm.count(reply_norm)


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
    if len(text) > 360:
        text = text[:357].rsplit(" ", 1)[0] + "..."
    return text


# Backward-compatible helper from the original repo.
def extract_fact(facts: str, label: str) -> str | None:
    pattern = rf"{re.escape(label)}:\s*([^.;]+)"
    match = re.search(pattern, facts)
    if not match:
        return None
    return match.group(1).strip()
