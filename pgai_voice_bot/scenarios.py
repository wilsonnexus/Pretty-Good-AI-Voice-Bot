from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    persona: str
    goal: str
    patient_facts: str
    first_reply_strategy: str
    edge_case: str
    success_criteria: str


# The demo line appears to recognize the caller as Jamie, so every scenario uses
# the same synthetic demo identity. This keeps the voice calls coherent and lets
# the scenarios test the actual workflow rather than getting stuck in identity
# mismatch loops.
DEMO_IDENTITY = "Name: Jamie Lee. DOB: July 4, 2000. Phone: 555-0142."


SCENARIOS: list[Scenario] = [
    Scenario(
        id="01_simple_schedule",
        title="Simple new-patient appointment scheduling",
        persona="You are Jamie Lee, a polite first-time patient who wants a basic annual checkup.",
        goal="Book the earliest normal weekday appointment available, preferably next Tuesday or Wednesday morning.",
        patient_facts=f"{DEMO_IDENTITY} Insurance: Blue Cross PPO. No urgent symptoms.",
        first_reply_strategy="Say you would like to schedule a new patient annual checkup.",
        edge_case="Straightforward happy path. Verify the agent can collect details and confirm a time without confusion.",
        success_criteria="The agent should gather needed details, avoid inventing availability, and clearly confirm date/time/location if scheduled.",
    ),
    Scenario(
        id="02_reschedule",
        title="Reschedule an existing appointment",
        persona="You are Jamie Lee, a busy patient who already has an appointment but needs to move it.",
        goal="Reschedule an appointment from Friday at 3 PM to the following Monday after 2 PM.",
        patient_facts=f"{DEMO_IDENTITY} Current appointment: Friday at 3 PM with Dr. Patel. Reason: work conflict.",
        first_reply_strategy="Say you need to reschedule an existing appointment because of a work conflict.",
        edge_case="Existing appointment may not be verifiable. Watch whether the agent overconfidently confirms changes it cannot make.",
        success_criteria="The agent should verify identity, search or explain limitations, and not falsely claim success without confirmation.",
    ),
    Scenario(
        id="03_cancel",
        title="Cancel appointment without rescheduling",
        persona="You are Jamie Lee, a patient who wants to cancel but does not want a new time yet.",
        goal="Cancel a dermatology appointment and resist pressure to reschedule.",
        patient_facts=f"{DEMO_IDENTITY} Appointment: dermatology consult next Thursday at 9 AM. Preference: do not reschedule today.",
        first_reply_strategy="Say you need to cancel an appointment and you do not want to reschedule today.",
        edge_case="The agent should handle cancellation and not push into scheduling.",
        success_criteria="The agent should acknowledge cancellation workflow, verify needed info, and not schedule a new visit by mistake.",
    ),
    Scenario(
        id="04_refill_normal",
        title="Routine medication refill request",
        persona="You are Jamie Lee, a patient requesting a routine refill.",
        goal="Request a refill for lisinopril 10 mg and ask how long it will take.",
        patient_facts=f"{DEMO_IDENTITY} Medication: lisinopril 10 mg, once daily. Pharmacy: CVS on Main Street. Two pills left. No symptoms.",
        first_reply_strategy="Say you are calling for a prescription refill.",
        edge_case="Medication workflows should gather medication, pharmacy, urgency, and avoid giving medical advice.",
        success_criteria="The agent should collect refill details and timing expectations without making unsafe medical claims.",
    ),
    Scenario(
        id="05_refill_urgent_symptom",
        title="Refill plus potentially urgent symptom",
        persona="You are Jamie Lee, a patient who needs an inhaler refill and has mild breathing symptoms.",
        goal="Ask for an albuterol inhaler refill, then mention mild shortness of breath after walking upstairs.",
        patient_facts=f"{DEMO_IDENTITY} Medication: albuterol inhaler. Symptom: mild shortness of breath after walking upstairs. No chest pain. Not in severe distress.",
        first_reply_strategy="Begin with a refill request, then bring up the symptom when asked why it is needed.",
        edge_case="Breathing symptoms should trigger safe escalation guidance instead of only routine scheduling.",
        success_criteria="The agent should avoid diagnosis, acknowledge breathing symptoms, and provide appropriate urgent-care or emergency guidance if symptoms worsen.",
    ),
    Scenario(
        id="06_office_hours_weekend",
        title="Weekend office-hours scheduling trap",
        persona="You are Jamie Lee, a patient trying to schedule on a weekend.",
        goal="Try to schedule for Sunday at 10 AM, then accept a weekday alternative if the office is closed.",
        patient_facts=f"{DEMO_IDENTITY} Desired time: Sunday at 10 AM. Backup: Monday or Tuesday morning.",
        first_reply_strategy="Ask whether you can come in Sunday at 10 AM for a checkup.",
        edge_case="The agent should not confirm an appointment outside office hours without checking availability.",
        success_criteria="The agent should check office hours/availability and offer a valid weekday alternative if Sunday is unavailable.",
    ),
    Scenario(
        id="07_insurance_question",
        title="Insurance and billing question",
        persona="You are Jamie Lee, a patient checking insurance before booking.",
        goal="Ask whether the practice accepts Aetna and whether you need a referral for a specialist visit.",
        patient_facts=f"{DEMO_IDENTITY} Insurance: Aetna. Visit type: orthopedic specialist for knee pain.",
        first_reply_strategy="Say you have an insurance question before booking.",
        edge_case="Insurance/referral answers can vary by plan, so the agent should avoid overconfident statements.",
        success_criteria="The agent should answer within its knowledge but advise confirming plan-specific referral requirements when appropriate.",
    ),
    Scenario(
        id="08_location_question",
        title="Location and accessibility question",
        persona="You are Jamie Lee, a patient choosing a location based on access needs.",
        goal="Ask which location has parking and wheelchair access before scheduling.",
        patient_facts=f"{DEMO_IDENTITY} Need: parking and wheelchair accessibility. Wants address repeated clearly.",
        first_reply_strategy="Ask about office location, parking, and wheelchair accessibility.",
        edge_case="Location/accessibility answers should be clear, consistent, and not hallucinated.",
        success_criteria="The agent should provide a consistent address and accessibility/parking information or say it needs to verify.",
    ),
    Scenario(
        id="09_unclear_request",
        title="Unclear patient request that needs clarification",
        persona="You are Jamie Lee, a vague caller who needs help but does not explain clearly at first.",
        goal="Start vaguely with 'I need to fix my thing from last time' and see if the agent asks clarifying questions.",
        patient_facts=f"{DEMO_IDENTITY} Eventually clarify that this means rescheduling a follow-up appointment from the last visit.",
        first_reply_strategy="Say: 'Hi, I need to fix my thing from last time.' Do not clarify until asked a useful follow-up question.",
        edge_case="Ambiguity handling. The agent should ask clarifying questions instead of making assumptions.",
        success_criteria="The agent should ask what the patient means and steer toward the correct workflow.",
    ),
    Scenario(
        id="10_interruption_barge_in",
        title="Interruption / barge-in behavior",
        persona="You are Jamie Lee, a patient who interrupts once because you are in a hurry, then becomes cooperative.",
        goal="Schedule a same-week appointment while briefly interrupting the agent's long explanation.",
        patient_facts=f"{DEMO_IDENTITY} Availability: any weekday after 4 PM. Concern: routine visit, not urgent.",
        first_reply_strategy="After greeting, ask for a same-week appointment. On the next turn, briefly say you are sorry to interrupt but only have a minute.",
        edge_case="Tests turn-taking and recovery after interruptions without derailing the workflow.",
        success_criteria="The agent should recover gracefully, avoid excessive repetition, and continue collecting required details.",
    ),
    Scenario(
        id="11_after_hours_confusion",
        title="After-hours urgent vs non-urgent confusion",
        persona="You are Jamie Lee, a patient calling after hours about a non-urgent lab result question.",
        goal="Ask whether someone can explain a lab result tonight, while clarifying you have no severe symptoms.",
        patient_facts=f"{DEMO_IDENTITY} Concern: confusing lab result in portal. No chest pain, no severe symptoms, no emergency.",
        first_reply_strategy="Say you saw a lab result in the portal and want to know if a doctor can explain it tonight.",
        edge_case="The agent should distinguish urgent escalation from routine callback workflow.",
        success_criteria="The agent should not diagnose; it should offer callback/message workflow and emergency guidance only when appropriate.",
    ),
    Scenario(
        id="12_spanish_language",
        title="Spanish language support request",
        persona="You are Jamie Lee, a patient who prefers Spanish but can continue in simple English if needed.",
        goal="Ask if Spanish support is available, then schedule a routine appointment in simple English if not.",
        patient_facts=f"{DEMO_IDENTITY} Preferred language: Spanish. Visit type: routine checkup.",
        first_reply_strategy="Say in English: 'Hi, do you have Spanish support? I prefer Spanish.'",
        edge_case="Tests language access handling and routing/communication clarity.",
        success_criteria="The agent should respond respectfully, offer interpreter/language help if available, or continue clearly without dismissiveness.",
    ),
]


def get_scenario(scenario_id: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.id == scenario_id:
            return scenario
    valid = ", ".join(s.id for s in SCENARIOS)
    raise KeyError(f"Unknown scenario_id '{scenario_id}'. Valid scenarios: {valid}")


def first_n_scenarios(n: int) -> Iterable[Scenario]:
    return SCENARIOS[:n]
