from __future__ import annotations

import os
import re
from typing import Any

import requests
from flask import Flask, Response, request
from twilio.twiml.voice_response import Gather, VoiceResponse

from .config import DEFAULT_ASSESSMENT_NUMBER, get_settings
from .llm import PatientResponder
from .scenarios import get_scenario
from .store import append_turn, load_state, read_transcript, save_state, update_metadata

app = Flask(__name__)
responder = PatientResponder()


@app.get("/health")
def health() -> tuple[dict[str, str], int]:
    return {"status": "ok"}, 200


@app.route("/voice/start", methods=["GET", "POST"])
def voice_start() -> Response:
    """First TwiML after the outbound call connects.

    The bot does not speak first. It listens for a real agent prompt. This avoids
    the common failure mode where both voice agents greet at the same time.
    """
    settings = get_settings(require_twilio=False)
    scenario_id = request.args.get("scenario_id", "01_simple_schedule")
    scenario = get_scenario(scenario_id)
    call_sid = request.values.get("CallSid", f"LOCAL-{scenario_id}")

    state = load_state(call_sid)
    if not state:
        save_state(
            call_sid,
            {
                "call_sid": call_sid,
                "scenario_id": scenario_id,
                "scenario_title": scenario.title,
                "turn_index": 0,
                "done": False,
                "silent_waits": 0,
            },
        )
        update_metadata(call_sid, scenario_id=scenario_id, scenario_title=scenario.title)

    response = VoiceResponse()
    response.append(make_gather(settings, scenario_id, 0))
    response.redirect(f"/voice/reply?scenario_id={scenario_id}&turn=0", method="POST")
    return twiml(response)


@app.route("/voice/reply", methods=["GET", "POST"])
def voice_reply() -> Response:
    settings = get_settings(require_twilio=False)
    scenario_id = request.args.get("scenario_id", "01_simple_schedule")
    scenario = get_scenario(scenario_id)
    call_sid = request.values.get("CallSid", f"LOCAL-{scenario_id}")
    turn_index = int(request.args.get("turn", "0"))

    state = load_state(call_sid) or {
        "call_sid": call_sid,
        "scenario_id": scenario_id,
        "scenario_title": scenario.title,
        "turn_index": turn_index,
        "done": False,
        "silent_waits": 0,
    }

    speech_result = request.values.get("SpeechResult", "").strip()
    confidence = request.values.get("Confidence")

    if speech_result:
        append_turn(call_sid, "agent", speech_result, turn_index=turn_index, confidence=confidence)
    elif turn_index == 0:
        append_turn(call_sid, "agent", "(No greeting detected before patient spoke.)", turn_index=turn_index)
    else:
        append_turn(call_sid, "agent", "(No clear speech detected.)", turn_index=turn_index)

    # If the agent only gave a recording disclosure, a filler acknowledgement, or
    # a "let me check" processing phrase, keep listening silently instead of
    # making the patient jump in. This is the main fix for start-of-call overlap
    # and mid-call interruption while the agent is still thinking.
    agent_text = speech_result or ""
    silent_waits = int(state.get("silent_waits", 0) or 0)
    if should_keep_listening(agent_text, turn_index, silent_waits):
        state["silent_waits"] = silent_waits + 1
        save_state(call_sid, state)
        response = VoiceResponse()
        response.append(make_gather(settings, scenario_id, turn_index))
        response.redirect(f"/voice/reply?scenario_id={scenario_id}&turn={turn_index}", method="POST")
        return twiml(response)

    transcript = read_transcript(call_sid)
    decision = responder.next_reply(scenario, transcript, turn_index)
    append_turn(call_sid, "patient", decision.reply, turn_index=turn_index)

    state.update(
        {
            "call_sid": call_sid,
            "scenario_id": scenario_id,
            "scenario_title": scenario.title,
            "turn_index": turn_index + 1,
            "done": decision.done,
            "last_llm_notes": decision.notes,
            "silent_waits": 0,
        }
    )
    save_state(call_sid, state)

    response = VoiceResponse()

    if settings.pre_reply_pause_seconds > 0:
        response.pause(length=settings.pre_reply_pause_seconds)

    response.say(decision.reply, voice=settings.twilio_voice)

    should_end = decision.done or (turn_index + 1) >= settings.max_turns_per_call
    if should_end:
        if settings.post_goodbye_pause_seconds > 0:
            response.pause(length=settings.post_goodbye_pause_seconds)
        response.hangup()
        return twiml(response)

    response.append(make_gather(settings, scenario_id, turn_index + 1))
    response.redirect(f"/voice/reply?scenario_id={scenario_id}&turn={turn_index + 1}", method="POST")
    return twiml(response)


@app.post("/voice/status")
def voice_status() -> tuple[dict[str, str], int]:
    call_sid = request.values.get("CallSid", "UNKNOWN")
    fields: dict[str, Any] = {k: request.values.get(k) for k in request.values.keys()}
    update_metadata(call_sid, status_callback=fields)
    return {"ok": "true"}, 200


@app.post("/voice/recording")
def recording_callback() -> tuple[dict[str, str], int]:
    """Download the final call recording when Twilio says it is available."""
    settings = get_settings(require_twilio=False)
    call_sid = request.values.get("CallSid", "UNKNOWN")
    recording_sid = request.values.get("RecordingSid", "UNKNOWN")
    recording_url = request.values.get("RecordingUrl", "")
    recording_status = request.values.get("RecordingStatus", "")

    update_metadata(
        call_sid,
        recording_sid=recording_sid,
        recording_url=recording_url,
        recording_status=recording_status,
        recording_callback=dict(request.values),
    )

    if recording_url and recording_status == "completed":
        try:
            mp3_url = recording_url + ".mp3"
            target_dir = os.path.join("data", "calls", call_sid)
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, "recording.mp3")
            resp = requests.get(
                mp3_url,
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                timeout=60,
            )
            resp.raise_for_status()
            with open(target_path, "wb") as f:
                f.write(resp.content)
            update_metadata(call_sid, recording_file=target_path)
        except Exception as exc:
            update_metadata(call_sid, recording_download_error=str(exc))
    return {"ok": "true"}, 200


def make_gather(settings: Any, scenario_id: str, turn: int) -> Gather:
    return Gather(
        input="speech",
        action=f"/voice/reply?scenario_id={scenario_id}&turn={turn}",
        method="POST",
        timeout=settings.speech_gather_timeout_seconds,
        speech_timeout=settings.twilio_speech_timeout,
        action_on_empty_result=True,
        profanity_filter=False,
    )


def should_keep_listening(agent_text: str, turn_index: int, silent_waits: int) -> bool:
    """Return True when the patient should stay silent and keep listening.

    Limit repeated silent waits so a broken call does not hang forever.
    """
    if silent_waits >= 2:
        return False

    text = normalize_for_wait(agent_text)
    if not text:
        return turn_index == 0 and silent_waits < 1

    if is_recording_disclosure_only(text):
        return True

    # After the patient provides DOB, the agent often says only "Great Jamie" or
    # "Thank you" and then continues. Do not speak during that filler phrase.
    if is_short_acknowledgement_only(text):
        return True

    # Do not respond to processing fragments such as "Let me check..." unless
    # the same utterance also asks a real question or offers a specific option.
    if is_processing_only(text):
        return True

    return False


def normalize_for_wait(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9: .,'?-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_recording_disclosure_only(text: str) -> bool:
    has_disclosure = "recorded" in text and ("quality" in text or "training" in text or "call may" in text)
    if not has_disclosure:
        return False
    meaningful_prompt_words = [
        "am i speaking",
        "are you",
        "date of birth",
        "how can i help",
        "what can i help",
        "appointment",
        "medication",
        "refill",
        "insurance",
        "location",
    ]
    return not any(word in text for word in meaningful_prompt_words)


def is_short_acknowledgement_only(text: str) -> bool:
    stripped = text.strip(" .?!,;")
    if stripped in {"thank you", "thanks", "great", "okay", "ok", "got it", "understood"}:
        return True
    # Wait on "Great Jamie" but not on a single "Jamie" identity prompt.
    return bool(re.fullmatch(r"(great|thanks|thank you|okay|ok|got it|understood)\s+(jamie|janie|amy|jenny|cheney)", stripped))


def is_processing_only(text: str) -> bool:
    processing_markers = [
        "let me check",
        "one moment",
        "give me a moment",
        "while i check",
        "while i process",
        "i will check",
        "checking",
        "let me look",
        "please hold",
    ]
    if not any(marker in text for marker in processing_markers):
        return False
    question_or_offer_markers = [
        "?",
        "would you like",
        "do you want",
        "can you",
        "could you",
        "is that correct",
        "are you",
        "i have openings",
        "i have an opening",
        "there are no",
        "no openings",
        "no appointments",
        "the soonest",
        "next available",
    ]
    return not any(marker in text for marker in question_or_offer_markers)


def twiml(response: VoiceResponse) -> Response:
    return Response(str(response), mimetype="text/xml")


if __name__ == "__main__":
    if get_settings(require_twilio=False).assessment_number != DEFAULT_ASSESSMENT_NUMBER:
        raise RuntimeError("Assessment number was changed. Refusing to start.")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
