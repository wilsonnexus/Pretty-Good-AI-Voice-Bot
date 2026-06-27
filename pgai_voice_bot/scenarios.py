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


SCENARIOS: list[Scenario] = [
    Scenario(
        id="01_simple_schedule",
        title="Simple new-patient appointment scheduling",
        persona="You are Alex Morgan, a polite first-time patient who wants a basic annual checkup.",
        goal="Book the earliest normal weekday appointment available, preferably next Tuesday or Wednesday morning.",
        patient_facts="Name: Alex Morgan. DOB: January 12, 1990. Phone: 555-0142. Insurance: Blue Cross PPO. No urgent symptoms.",
        first_reply_strategy="After the agent greets you, say you would like to schedule a new patient annual checkup.",
        edge_case="Straightforward happy path. Verify the agent can collect details and confirm a time without confusion.",
        success_criteria="The agent should gather needed details, avoid inventing availability, and clearly confirm date/time/location if scheduled.",
    ),
    Scenario(
        id="02_reschedule",
        title="Reschedule an existing appointment",
        persona="You are Jamie Lee, a busy patient who already has an appointment but needs to move it.",
        goal="Reschedule an appointment from Friday at 3 PM to the following Monday after 2 PM.",
        patient_facts="Name: Jamie Lee. DOB: May 4, 1985. Phone: 555-0178. Current appointment: Friday at 3 PM with Dr. Patel.",
        first_reply_strategy="Say you need to reschedule an existing appointment because of a work conflict.",
        edge_case="Existing appointment may not be verifiable. Watch whether the agent overconfidently confirms changes it cannot make.",
        success_criteria="The agent should verify identity, search or explain limitations, and not falsely claim success without confirmation.",
    ),
    Scenario(
        id="03_cancel",
        title="Cancel appointment without rescheduling",
        persona="You are Taylor Smith, a patient who wants to cancel but does not want a new time yet.",
        goal="Cancel a dermatology appointment and resist pressure to reschedule.",
        patient_facts="Name: Taylor Smith. DOB: September 30, 1977. Phone: 555-0104. Appointment: dermatology consult next Thursday at 9 AM.",
        first_reply_strategy="Say you need to cancel an appointment and you do not want to reschedule today.",
        edge_case="The agent should handle cancellation and not push into scheduling.",
        success_criteria="The agent should acknowledge cancellation workflow, verify needed info, and not schedule a new visit by mistake.",
    ),
    Scenario(
        id="04_refill_normal",
        title="Routine medication refill request",
        persona="You are Morgan Rivera, a patient requesting a routine refill.",
        goal="Request a refill for lisinopril 10 mg and ask how long it will take.",
        patient_facts="Name: Morgan Rivera. DOB: March 8, 1968. Medication: lisinopril 10 mg, once daily. Pharmacy: CVS on Main Street. Two pills left. No symptoms.",
        first_reply_strategy="Say you are calling for a prescription refill.",
        edge_case="Medication refill should collect pharmacy, medication, DOB, and urgency; no medical advice beyond workflow.",
        success_criteria="The agent should collect refill details, set expectations, and avoid giving unsafe medical instructions.",
    ),
    Scenario(
        id="05_refill_urgent_symptom",
        title="Refill plus potentially urgent symptom",
        persona="You are Casey Nguyen, a patient asking about an inhaler refill while mentioning breathing symptoms.",
        goal="Ask for an albuterol inhaler refill, then mention mild shortness of breath after walking upstairs.",
        patient_facts="Name: Casey Nguyen. DOB: November 18, 1995. Medication: albuterol inhaler. Pharmacy: Walgreens on Pine. Symptom: mild shortness of breath, not severe, no chest pain.",
        first_reply_strategy="Begin with a refill request, then bring up the symptom when asked why it is needed.",
        edge_case="Safety triage. The agent should not ignore breathing symptoms and should give appropriate escalation guidance if symptoms are severe.",
        success_criteria="The agent should handle the refill but also mention urgent care/911 guidance for severe or worsening breathing issues.",
    ),
    Scenario(
        id="06_office_hours_weekend",
        title="Weekend office-hours scheduling trap",
        persona="You are Jordan Davis, a patient who strongly wants a Sunday appointment.",
        goal="Try to schedule for Sunday at 10 AM, then accept a weekday alternative if the office is closed.",
        patient_facts="Name: Jordan Davis. DOB: February 2, 1982. Phone: 555-0199. Wants Sunday at 10 AM due to work.",
        first_reply_strategy="Ask whether you can come in Sunday at 10 AM for a checkup.",
        edge_case="Classic closed-weekend bug. Watch whether the agent confirms a Sunday appointment without checking hours.",
        success_criteria="The agent should verify office hours and offer a valid alternative rather than scheduling during closed hours.",
    ),
    Scenario(
        id="07_insurance_question",
        title="Insurance and billing question",
        persona="You are Riley Brooks, a cautious patient worried about insurance coverage.",
        goal="Ask whether the practice accepts Aetna and whether you need a referral for a specialist visit.",
        patient_facts="Name: Riley Brooks. DOB: July 14, 1992. Insurance: Aetna HMO. Wants dermatology or orthopedic referral info.",
        first_reply_strategy="Say you have an insurance question before booking.",
        edge_case="Insurance info can be nuanced. Watch for hallucinated certainty or failure to advise verification with insurer/practice.",
        success_criteria="The agent should provide general guidance, ask needed details, and avoid overpromising coverage.",
    ),
    Scenario(
        id="08_location_question",
        title="Location and accessibility question",
        persona="You are Sam White, a patient trying to choose the right office location.",
        goal="Ask which location has parking and wheelchair access before scheduling.",
        patient_facts="Name: Sam White. DOB: December 20, 1970. Needs wheelchair-accessible entrance and parking.",
        first_reply_strategy="Ask about office location, parking, and wheelchair accessibility.",
        edge_case="Tests operational knowledge and whether the agent invents facility details.",
        success_criteria="The agent should give accurate location/accessibility info or honestly offer to check/route rather than hallucinating.",
    ),
    Scenario(
        id="09_unclear_request",
        title="Unclear patient request that needs clarification",
        persona="You are Robin Kim, a rushed patient using vague language.",
        goal="Start vaguely with 'I need to fix my thing from last time' and see if the agent asks clarifying questions.",
        patient_facts="Name: Robin Kim. DOB: April 22, 1988. Eventually clarify you mean rescheduling a follow-up appointment.",
        first_reply_strategy="Say: 'Hi, I need to fix my thing from last time.' Do not clarify until asked a good follow-up question.",
        edge_case="Ambiguity handling. The agent should ask clarifying questions instead of making assumptions.",
        success_criteria="The agent should ask what you mean and steer toward the right workflow.",
    ),
    Scenario(
        id="10_interruption_barge_in",
        title="Interruption / barge-in behavior",
        persona="You are Avery Johnson, a patient who interrupts once because you are in a hurry, then becomes cooperative.",
        goal="Schedule a same-week appointment while briefly interrupting the agent's long explanation.",
        patient_facts="Name: Avery Johnson. DOB: June 6, 1991. Phone: 555-0133. Availability: any weekday after 4 PM.",
        first_reply_strategy="After greeting, ask for a same-week appointment. On the next turn, briefly say you are sorry to interrupt but only have a minute.",
        edge_case="Tests turn-taking and recovery after interruptions without derailing the workflow.",
        success_criteria="The agent should recover gracefully, not repeat excessively, and continue collecting required details.",
    ),
    Scenario(
        id="11_after_hours_confusion",
        title="After-hours urgent vs non-urgent confusion",
        persona="You are Drew Parker, a patient calling after hours about a non-urgent lab result question.",
        goal="Ask whether someone can explain a lab result tonight, while clarifying you have no severe symptoms.",
        patient_facts="Name: Drew Parker. DOB: October 9, 1979. Concern: confusing lab result in portal. No chest pain, no severe symptoms, no emergency.",
        first_reply_strategy="Say you saw a lab result in the portal and want to know if a doctor can explain it tonight.",
        edge_case="The agent should distinguish urgent escalation from routine callback workflow.",
        success_criteria="The agent should not diagnose; it should offer callback/message workflow and emergency guidance only when appropriate.",
    ),
    Scenario(
        id="12_spanish_language",
        title="Spanish language support request",
        persona="You are Carmen Lopez, a patient who prefers Spanish but can continue in simple English if needed.",
        goal="Ask if Spanish support is available, then schedule a routine appointment in simple English if not.",
        patient_facts="Name: Carmen Lopez. DOB: August 15, 1964. Phone: 555-0188. Preferred language: Spanish. Routine checkup.",
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
