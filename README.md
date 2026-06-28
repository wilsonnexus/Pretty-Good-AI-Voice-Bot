# Pretty Good AI Voice Bot Challenge

This repository is my Python voice-bot caller for the Pretty Good AI AI Engineering Challenge.

The bot calls only the official assessment line:

```text
+1-805-439-8008
```

It acts as a realistic patient, carries out healthcare-related test scenarios, records the calls, saves transcripts, exports deliverables, and generates a bug report from the conversations.

## Submission Summary

This submission includes:

- Working Python voice bot code
- Twilio outbound call launcher locked to the required assessment number
- Flask webhook server for handling voice turns
- Realistic patient scenarios for scheduling, rescheduling, cancellation, refills, insurance, office hours, location questions, unclear requests, and interruption handling
- Call transcripts with both sides of the conversation
- MP3 recordings of the calls
- Bug report with severity, evidence, and expected behavior
- Architecture document
- `.env.example` showing required environment variables without exposing secrets

The final deliverables include **10 complete calls** with both transcript and MP3 recording files, meeting the 10-call minimum requirement.

## Repository Structure

```text
.
├── README.md
├── ARCHITECTURE.md
├── .env.example
├── requirements.txt
├── pgai_voice_bot/
│   ├── web.py
│   ├── make_calls.py
│   ├── scenarios.py
│   ├── config.py
│   ├── store.py
│   ├── export_deliverables.py
│   ├── analyze_bugs.py
│   └── llm.py
├── deliverables/
│   ├── CALL_INDEX.md
│   ├── transcripts/
│   ├── recordings/
│   └── bug_reports/
├── scripts/
└── tests/
```

## What the Bot Does

The bot places outbound calls through Twilio and uses a Flask webhook server to control the conversation.

For each call, the bot is given a patient scenario and a goal. It then responds to the Pretty Good AI agent using short, realistic patient turns instead of simply reading a fixed script. This makes the calls more like real patient interactions and allows the bot to test how the agent handles ambiguity, missing information, and edge cases.

The bot records and stores:

- Call metadata
- Scenario name
- Transcript turns
- Twilio recording files
- Exported MP3 recordings
- Bug-analysis output

## Scenarios Tested

The main test scenarios include:

1. Simple new-patient appointment scheduling
2. Rescheduling an existing appointment
3. Canceling an appointment without rescheduling
4. Routine medication refill request
5. Medication refill with potentially urgent symptoms
6. Weekend office-hours scheduling edge case
7. Insurance and billing question
8. Location and accessibility question
9. Unclear patient request requiring clarification
10. Interruption / barge-in behavior

These scenarios were chosen because they represent common healthcare voice-agent workflows while also testing failure modes such as unclear intent, unsafe medical escalation, identity mismatch, and poor turn-taking recovery.

## Deliverables

The main deliverables are in the `deliverables/` folder:

```text
deliverables/CALL_INDEX.md
deliverables/transcripts/
deliverables/recordings/
deliverables/bug_reports/bug_report.md
```

`CALL_INDEX.md` lists every attempted call and whether its transcript and recording were successfully exported.

The completed calls have:

- A `.txt` transcript file
- A `.mp3` recording file
- A scenario label
- A Twilio Call SID

Calls marked `MISSING` were incomplete attempts and are not counted toward the final evaluated call set.

## Prerequisites

To run this project, you need:

1. Python 3.10+
2. A Twilio account
3. One Twilio Voice-capable phone number
4. ngrok or another public tunnel provider
5. Optional: an OpenAI API key for adaptive patient responses and bug-analysis assistance

You also need to create a test account at:

```text
pgai.us/athena
```

That gives product context for the patient experience. Do not call the number shown on that confirmation screen. This project is locked to the official assessment number only.

## Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Then fill in:

```bash
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_FROM_NUMBER=+1YOURTWILIONUMBER
PUBLIC_BASE_URL=https://your-ngrok-url.ngrok-free.app
OPENAI_API_KEY=sk-proj-your-key
OPENAI_MODEL=gpt-4o-mini
ASSESSMENT_NUMBER=+18054398008
```

Do not change:

```bash
ASSESSMENT_NUMBER=+18054398008
```

The code validates this value and refuses to call any other number.

Do not commit `.env`.

## Setup on macOS / Linux

```bash
git clone https://github.com/wilsonnexus/Pretty-Good-AI-Voice-Bot.git
cd Pretty-Good-AI-Voice-Bot

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
```

Then edit `.env` with your Twilio, ngrok, and optional OpenAI values.

## Setup on Windows Git Bash

```bash
git clone https://github.com/wilsonnexus/Pretty-Good-AI-Voice-Bot.git
cd Pretty-Good-AI-Voice-Bot

python -m venv .venv
source .venv/Scripts/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cp .env.example .env
notepad .env
```

On Windows, the virtual environment activation path is:

```bash
source .venv/Scripts/activate
```

not:

```bash
source .venv/bin/activate
```

## Running Locally

Start the Flask webhook server:

```bash
python -m pgai_voice_bot.web
```

In another terminal, expose port `5000` publicly:

```bash
ngrok http 5000
```

Copy the HTTPS ngrok forwarding URL into `.env` as:

```bash
PUBLIC_BASE_URL=https://your-ngrok-url.ngrok-free.app
```

Then restart the Flask server.

## Dry Run

Before making real calls, run:

```bash
python -m pgai_voice_bot.make_calls --all --count 10 --dry-run
```

This verifies the configured scenarios and call plan without placing calls.

## Making Real Calls

To place the first 10 scenario calls:

```bash
python -m pgai_voice_bot.make_calls --all --count 10 --delay 180
```

The delay prevents calls from overlapping.

A single scenario can also be tested:

```bash
python -m pgai_voice_bot.make_calls 06_office_hours_weekend --delay 180
```

## Exporting Deliverables

After the calls finish and Twilio recording callbacks complete, run:

```bash
python -m pgai_voice_bot.export_deliverables
python -m pgai_voice_bot.analyze_bugs
```

Then review:

```bash
cat deliverables/CALL_INDEX.md
cat deliverables/bug_reports/bug_report.md
```

On Windows, you can open the deliverables folder with:

```bash
explorer deliverables
```

## Bug Report

The bug report is stored at:

```text
deliverables/bug_reports/bug_report.md
```

It includes candidate issues found during testing, including examples such as:

- Cancellation flow problems
- Identity-verification weakness during refill flow
- Missing urgent-care escalation for breathing symptoms
- Office-hours validation issues
- Inconsistent or unclear location/accessibility responses
- Poor recovery from vague requests or interruptions

Each issue should be manually reviewed against the transcript and audio.

## Design Choices

I kept the design intentionally simple because the challenge prioritizes working calls, clear reasoning, and fast iteration over production-grade infrastructure.

The main pieces are:

- Twilio for outbound calling, speech input, and call recording
- Flask for webhook endpoints
- Scenario definitions for patient goals
- Transcript storage for both sides of the conversation
- Export scripts to create the required GitHub deliverables
- Optional LLM support for more adaptive responses and bug analysis

The bot is structured so that scenarios, call placement, webhook handling, exports, and bug analysis are separated into readable modules.

## Safety Guardrails

This project is for the Pretty Good AI assessment only.

The code hardcodes and validates the assessment number:

```text
+1-805-439-8008
```

It should not be used to call any other number.

Do not commit:

- `.env`
- Twilio credentials
- OpenAI API keys
- Real patient information
- Any private healthcare data
