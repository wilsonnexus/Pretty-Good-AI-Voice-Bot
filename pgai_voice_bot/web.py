from __future__ import annotations

import os
from typing import Any

import requests
from flask import Flask, Response, jsonify, request
from twilio.twiml.voice_response import Gather, Pause, VoiceResponse

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

    We listen before speaking so the PG AI agent can say its greeting first. That
    avoids overlapping the agent's introduction.
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
            },
        )
        update_metadata(call_sid, scenario_id=scenario_id, scenario_title=scenario.title)

    response = VoiceResponse()
    gather = Gather(
        input="speech",
        action=f"/voice/reply?scenario_id={scenario_id}&turn=0",
        method="POST",
        timeout=settings.speech_gather_timeout_seconds,
        speech_timeout="2",
        action_on_empty_result=True,
        profanity_filter=False,
    )
    gather.append(Pause(length=1))
    response.append(gather)
    # If Twilio falls through, force the first reply.
    response.redirect(f"/voice/reply?scenario_id={scenario_id}&turn=0", method="POST")
    return twiml(response)


@app.route("/voice/reply", methods=["GET", "POST"])
def voice_reply() -> Response:
    settings = get_settings(require_twilio=False)
    scenario_id = request.args.get("scenario_id", "01_simple_schedule")
    scenario = get_scenario(scenario_id)
    call_sid = request.values.get("CallSid", f"LOCAL-{scenario_id}")
    turn_index = int(request.args.get("turn", "0"))

    speech_result = request.values.get("SpeechResult", "").strip()
    confidence = request.values.get("Confidence")
    if speech_result:
        append_turn(call_sid, "agent", speech_result, turn_index=turn_index, confidence=confidence)
    elif turn_index == 0:
        append_turn(call_sid, "agent", "(No greeting detected before patient spoke.)", turn_index=turn_index)
    else:
        append_turn(call_sid, "agent", "(No clear speech detected.)", turn_index=turn_index)

    transcript = read_transcript(call_sid)
    decision = responder.next_reply(scenario, transcript, turn_index)
    append_turn(call_sid, "patient", decision.reply, turn_index=turn_index)

    state = load_state(call_sid)
    state.update(
        {
            "call_sid": call_sid,
            "scenario_id": scenario_id,
            "scenario_title": scenario.title,
            "turn_index": turn_index + 1,
            "done": decision.done,
            "last_llm_notes": decision.notes,
        }
    )
    save_state(call_sid, state)

    response = VoiceResponse()
    # Give the callee a small buffer after Twilio decides their turn ended.
    # This makes the caller sound less interruptive with voice agents that pause
    # briefly while thinking or streaming speech.
    response.pause(length=2)
    response.say(decision.reply, voice=settings.twilio_voice)

    should_end = decision.done or (turn_index + 1) >= settings.max_turns_per_call
    if should_end:
        # Leave a short pause after the final goodbye so the call does not feel
        # like an abrupt hangup.
        response.pause(length=3)
        response.hangup()
        return twiml(response)

    gather = Gather(
        input="speech",
        action=f"/voice/reply?scenario_id={scenario_id}&turn={turn_index + 1}",
        method="POST",
        timeout=settings.speech_gather_timeout_seconds,
        speech_timeout="2",
        action_on_empty_result=True,
        profanity_filter=False,
    )
    gather.append(Pause(length=1))
    response.append(gather)
    # Keep progressing even if speech recognition does not fire.
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
            # Twilio recording media can be fetched by adding an extension.
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


def twiml(response: VoiceResponse) -> Response:
    return Response(str(response), mimetype="text/xml")


if __name__ == "__main__":
    if get_settings(require_twilio=False).assessment_number != DEFAULT_ASSESSMENT_NUMBER:
        raise RuntimeError("Assessment number was changed. Refusing to start.")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
