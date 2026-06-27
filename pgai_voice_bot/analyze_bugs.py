from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rich.console import Console

from .config import DELIVERABLES_DIR, get_settings
from .scenarios import get_scenario
from .store import all_call_dirs

console = Console()

BUG_REPORT_HEADER = """# Bug Report

Generated candidate issues from the recorded/transcribed calls. Before submitting, listen to the audio and verify each issue manually. Delete anything that is not a real product issue.

| Severity | Call | Time/Turn | Issue | Why it matters | Evidence | Expected behavior |
|---|---|---|---|---|---|---|
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze transcripts and create a candidate bug report.")
    parser.add_argument("--manual-only", action="store_true", help="Create a blank review template without using OpenAI.")
    args = parser.parse_args()

    settings = get_settings(require_twilio=False)
    call_dirs = all_call_dirs()
    if not call_dirs:
        raise SystemExit("No calls found in data/calls. Run calls first.")

    report_rows: list[str] = []
    if args.manual_only or not settings.openai_api_key:
        report_rows = manual_template_rows(call_dirs)
    else:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        for idx, call_dir in enumerate(call_dirs, start=1):
            row = analyze_call_with_llm(client, settings.openai_model, idx, call_dir)
            if row:
                report_rows.append(row)

    out = BUG_REPORT_HEADER + "\n".join(report_rows) + "\n"
    target = DELIVERABLES_DIR / "bug_reports" / "bug_report.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(out, encoding="utf-8")
    console.print(f"Wrote {target}")


def manual_template_rows(call_dirs: list[Path]) -> list[str]:
    rows: list[str] = []
    for idx, call_dir in enumerate(call_dirs, start=1):
        scenario_id = scenario_id_for_call(call_dir)
        rows.append(
            f"| TBD | transcript-{idx:02d} | TBD | Review `{scenario_id}` manually | Listen to audio and inspect transcript | TBD | TBD |"
        )
    return rows


def analyze_call_with_llm(client: Any, model: str, idx: int, call_dir: Path) -> str:
    scenario_id = scenario_id_for_call(call_dir)
    try:
        scenario = get_scenario(scenario_id)
        scenario_text = (
            f"Scenario: {scenario.title}\nGoal: {scenario.goal}\nEdge case: {scenario.edge_case}\n"
            f"Success criteria: {scenario.success_criteria}"
        )
    except Exception:
        scenario_text = f"Scenario ID: {scenario_id}"

    transcript_path = call_dir / "transcript.txt"
    if not transcript_path.exists():
        return f"| TBD | transcript-{idx:02d} | TBD | Missing transcript | Cannot evaluate this call yet | No transcript file | Ensure transcript is exported |"
    transcript = transcript_path.read_text(encoding="utf-8")

    instructions = """
You are reviewing a healthcare voice AI assessment transcript. Identify only real, useful bugs or quality issues.
Do not nitpick punctuation. Do not invent facts not in the transcript. If no issue is clear, return an empty issues list.
Return strict JSON: {"issues":[{"severity":"High|Medium|Low","time_or_turn":"...","issue":"...","why":"...","evidence":"short quote/paraphrase","expected":"..."}]}
""".strip()

    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=f"{scenario_text}\n\nTranscript:\n{transcript}",
        temperature=0.2,
        max_output_tokens=700,
    )
    raw = getattr(response, "output_text", "") or "{}"
    data = parse_json(raw)
    issues = data.get("issues", []) if isinstance(data, dict) else []
    rows: list[str] = []
    for issue in issues[:3]:
        rows.append(
            "| {severity} | transcript-{idx:02d} | {time} | {issue} | {why} | {evidence} | {expected} |".format(
                severity=md_escape(str(issue.get("severity", "Medium"))),
                idx=idx,
                time=md_escape(str(issue.get("time_or_turn", "TBD"))),
                issue=md_escape(str(issue.get("issue", ""))),
                why=md_escape(str(issue.get("why", ""))),
                evidence=md_escape(str(issue.get("evidence", ""))),
                expected=md_escape(str(issue.get("expected", ""))),
            )
        )
    return "\n".join(rows)


def parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").replace("json", "", 1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
        return {"issues": []}


def scenario_id_for_call(call_dir: Path) -> str:
    for name in ["metadata.json", "state.json"]:
        p = call_dir / name
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("scenario_id"):
                    return data["scenario_id"]
            except Exception:
                pass
    return "unknown"


def md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()[:600]


if __name__ == "__main__":
    main()
