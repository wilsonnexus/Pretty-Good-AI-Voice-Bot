# Separate 5-Minute AI Debugging Recording Guide

The challenge asks for a 5-minute screen recording of you prompting AI to debug and fix your code. Record a real debugging session after you have a small issue. Here is a clean format.

## Good bug to demonstrate

Use a realistic small issue, for example:

- The bot is speaking too soon and overlapping the agent greeting.
- The transcript labels are confusing.
- Recording callback fires but MP3 is not exported.
- The LLM response is too long for a natural phone call.

## Recording structure

1. Show the bug in terminal or transcript.
2. Prompt AI with specific context.
3. Apply a small patch.
4. Run a smoke test or one real call.
5. Explain what improved and what you would test next.

## Example prompts to use on screen

Prompt 1:

```text
I am building a Twilio + Flask voice bot for an authorized assessment. The bot currently says the first patient line immediately after the call connects, which may overlap with the AI agent greeting. Inspect this Flask/TwiML flow and suggest the smallest code change so the bot listens first, captures the greeting if present, then replies.
```

Prompt 2:

```text
Here is my current /voice/start and /voice/reply code. Please identify why my first Gather might fall through without logging an agent turn. I want transcript logs to include either the agent greeting or a clear '(No greeting detected)' marker. Give me a minimal patch.
```

Prompt 3:

```text
Review this transcript from a test call. The patient bot response is too long and sounds unnatural over Twilio TTS. Rewrite the LLM instructions so replies stay under two sentences while still steering toward the scenario goal.
```

Prompt 4:

```text
I need to export all completed call recordings and transcripts into deliverables/ with stable names. Look at my export script and add checks that warn me when fewer than 10 calls or missing MP3 files are present.
```

End by saying what you accepted, what you rejected, and why.
