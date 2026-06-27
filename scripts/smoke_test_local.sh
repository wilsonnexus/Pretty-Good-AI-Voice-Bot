#!/usr/bin/env bash
set -euo pipefail

curl -s -X POST "http://localhost:5000/voice/start?scenario_id=06_office_hours_weekend" \
  -d "CallSid=LOCALSMOKE001" | head -c 500
printf "\n\n--- reply ---\n"
curl -s -X POST "http://localhost:5000/voice/reply?scenario_id=06_office_hours_weekend&turn=0" \
  -d "CallSid=LOCALSMOKE001" \
  -d "SpeechResult=Thank you for calling. How can I help you today?" \
  -d "Confidence=0.92" | head -c 1000
printf "\n"
