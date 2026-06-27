# Pretty Good AI Voice Bot Challenge

This repo is a Python voice-bot caller for the Pretty Good AI AI Engineering Challenge.
It calls only the official assessment line: `+1-805-439-8008`.

The bot acts as a realistic patient, listens to the Pretty Good AI agent, replies using short natural patient turns, records the calls, saves transcripts, and exports the required GitHub deliverables.

## What this includes

- Python Flask webhook app for Twilio voice calls
- Twilio outbound call launcher locked to the assessment number
- 12 realistic patient scenarios, with the first 10 covering the minimum requirement
- Transcript logging with both sides of the conversation
- Automatic MP3 recording download from Twilio recording callbacks
- Export script for `deliverables/transcripts/`, `deliverables/recordings/`, and `deliverables/CALL_INDEX.md`
- Bug report generator for candidate issues found in transcripts
- Setup files: `.env.example`, `requirements.txt`, architecture doc, Loom guide

## Prerequisites

1. Create a test account at `pgai.us/athena` to understand the product context. Do not call the number shown on its confirmation screen.
2. Create a Twilio account and get:
   - Account SID
   - Auth Token
   - One Twilio Voice-capable phone number in E.164 format, such as `+13334445555`
3. Create an OpenAI API key. The bot can run without it, but the adaptive LLM patient mode and bug analysis are much better with it.
4. Install ngrok or Cloudflare Tunnel so Twilio can reach your local Flask app.

## Fast setup

```bash
git clone <your-new-github-repo-url>
cd pgai_voice_bot_challenge
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```bash
nano .env
```

Set these values:

```bash
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_FROM_NUMBER=+1YOURTWILIONUMBER
PUBLIC_BASE_URL=https://your-ngrok-url.ngrok-free.app
OPENAI_API_KEY=sk-proj-your-key
```

Leave this value unchanged:

```bash
ASSESSMENT_NUMBER=+18054398008
```

## Run locally

Terminal 1: start Flask.

```bash
source .venv/bin/activate
python -m pgai_voice_bot.web
```

Terminal 2: expose Flask publicly.

```bash
ngrok http 5000
```

Copy the `https://...ngrok-free.app` URL into `.env` as `PUBLIC_BASE_URL`, then restart Flask.

Terminal 3: run a dry run first.

```bash
source .venv/bin/activate
python -m pgai_voice_bot.make_calls --all --count 10 --dry-run
```

Then place the real 10 calls sequentially. Default delay is 180 seconds so calls do not overlap.

```bash
python -m pgai_voice_bot.make_calls --all --count 10 --delay 180
```

You can also run one scenario while testing:

```bash
python -m pgai_voice_bot.make_calls 06_office_hours_weekend --delay 180
```

## Export deliverables

After the calls are complete and Twilio recording callbacks finish, run:

```bash
python -m pgai_voice_bot.export_deliverables
python -m pgai_voice_bot.analyze_bugs
```

Review everything manually before submitting. The final files to commit are:

```text
deliverables/CALL_INDEX.md
deliverables/transcripts/*.txt
deliverables/recordings/*.mp3
deliverables/bug_reports/bug_report.md
ARCHITECTURE.md
README.md
.env.example
```

If `CALL_INDEX.md` says a recording is missing, wait a minute and run export again. If it is still missing, check Twilio Console > Monitor > Logs > Calls > Recordings.

## Scenarios

Run the first 10 for the minimum requirement:

1. Simple new-patient appointment scheduling
2. Reschedule an existing appointment
3. Cancel appointment without rescheduling
4. Routine medication refill request
5. Refill plus potentially urgent symptom
6. Weekend office-hours scheduling trap
7. Insurance and billing question
8. Location and accessibility question
9. Unclear patient request that needs clarification
10. Interruption / barge-in behavior

Extra scenarios:

11. After-hours urgent vs non-urgent confusion
12. Spanish language support request

## Submission checklist

- [ ] Public GitHub repo link
- [ ] At least 10 full calls, typically 1 to 3 minutes each
- [ ] Audio recordings in MP3 or OGG format
- [ ] Text transcripts with both sides of each conversation
- [ ] Bug report with clear severity/evidence/expected behavior
- [ ] `README.md` setup/run instructions
- [ ] `ARCHITECTURE.md` with 1 to 2 paragraphs
- [ ] Loom walkthrough, max 5 minutes
- [ ] Separate 5-minute screen recording showing AI-assisted debugging
- [ ] The one caller phone number used, in E.164 format

## Safety guardrails

The code hardcodes and validates the assessment number. It refuses to run if `ASSESSMENT_NUMBER` is changed from `+18054398008`. Do not use this project to call anyone else.

Do not commit `.env`, Twilio credentials, OpenAI keys, or real patient information.
