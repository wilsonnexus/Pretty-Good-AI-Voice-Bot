# 5-Minute Loom Walkthrough Script

Use this as a guide. Do not read it robotically; show the repo and terminal while talking.

## 0:00-0:30 — Goal

"This project is a Python voice-bot caller for the Pretty Good AI AI Engineering Challenge. It calls only the official assessment number and behaves like a realistic patient to test scheduling, refill, insurance, location, and edge-case conversations."

Show `.env.example` and point out the locked `ASSESSMENT_NUMBER=+18054398008`.

## 0:30-1:30 — Architecture

Show `ARCHITECTURE.md`, then `pgai_voice_bot/web.py`.

Explain:

- Twilio places the outbound call.
- Flask returns TwiML.
- The first webhook listens for the PG AI greeting before speaking.
- Each turn is gathered, transcribed, saved, and used to generate the next patient response.
- Recordings are downloaded from Twilio's recording callback.

## 1:30-2:30 — Scenarios

Show `pgai_voice_bot/scenarios.py`.

Say:

"I used scenario-driven testing rather than random prompts. Each scenario has a persona, goal, patient facts, edge case, and success criteria. This lets the bot stay coherent while still pushing the agent into useful failure modes."

Point out these examples:

- Weekend scheduling trap
- Refill with breathing symptoms
- Unclear request requiring clarification
- Interruption/barge-in

## 2:30-3:30 — Running it

Show the README commands:

```bash
python -m pgai_voice_bot.web
ngrok http 5000
python -m pgai_voice_bot.make_calls --all --count 10 --delay 180
```

Show `deliverables/CALL_INDEX.md`, transcripts, recordings, and bug report if you have already run calls.

## 3:30-4:30 — What you learned / iteration

Say what you changed after early calls. Example:

"My first version spoke immediately after the call connected, which risked overlapping the agent greeting. I changed the first webhook to gather speech first, so the bot listens before responding. I also shortened patient responses because long TTS replies made the conversation feel less natural."

## 4:30-5:00 — Bugs found

Show `deliverables/bug_reports/bug_report.md`.

Pick one verified issue and explain:

- What happened
- Why it matters
- Where the transcript/recording evidence is
- What the expected behavior should be
