from __future__ import annotations

import argparse
import time
from typing import Iterable

from rich.console import Console
from twilio.rest import Client

from .config import DEFAULT_ASSESSMENT_NUMBER, get_settings, ensure_dirs
from .scenarios import SCENARIOS, get_scenario
from .store import update_metadata

console = Console()


def create_outbound_call(client: Client, scenario_id: str, dry_run: bool = False) -> str:
    settings = get_settings(require_twilio=True)
    if settings.assessment_number != DEFAULT_ASSESSMENT_NUMBER:
        raise RuntimeError("Refusing to call a non-assessment number.")

    scenario = get_scenario(scenario_id)
    start_url = f"{settings.public_base_url}/voice/start?scenario_id={scenario_id}"
    status_url = f"{settings.public_base_url}/voice/status"
    recording_url = f"{settings.public_base_url}/voice/recording"

    if dry_run:
        console.print(f"[yellow]DRY RUN[/yellow] Would call {settings.assessment_number} from {settings.twilio_from_number} for {scenario_id}: {scenario.title}")
        return f"DRYRUN-{scenario_id}"

    call = client.calls.create(
        to=settings.assessment_number,
        from_=settings.twilio_from_number,
        url=start_url,
        method="POST",
        status_callback=status_url,
        status_callback_event=["initiated", "ringing", "answered", "completed"],
        status_callback_method="POST",
        record=True,
        recording_status_callback=recording_url,
        recording_status_callback_event=["completed"],
        recording_status_callback_method="POST",
    )
    update_metadata(
        call.sid,
        scenario_id=scenario_id,
        scenario_title=scenario.title,
        twilio_call_sid=call.sid,
        to=settings.assessment_number,
        from_number=settings.twilio_from_number,
    )
    console.print(f"[green]Created call[/green] {call.sid} for {scenario_id}: {scenario.title}")
    return call.sid


def scenario_ids_for_args(args: argparse.Namespace) -> Iterable[str]:
    if args.all:
        return [s.id for s in SCENARIOS[: args.count]]
    return args.scenario_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Place authorized PG AI assessment calls only to +1-805-439-8008.")
    parser.add_argument("scenario_id", nargs="*", help="Scenario IDs to run. Omit with --all to run the first 10.")
    parser.add_argument("--all", action="store_true", help="Run the first N scenarios sequentially.")
    parser.add_argument("--count", type=int, default=10, help="Number of scenarios to run with --all. Default: 10.")
    parser.add_argument("--delay", type=int, default=180, help="Seconds to wait between calls. Default: 180.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned calls without placing them.")
    args = parser.parse_args()

    ensure_dirs()
    settings = get_settings(require_twilio=not args.dry_run)
    if settings.assessment_number != DEFAULT_ASSESSMENT_NUMBER:
        raise RuntimeError("Refusing to call a non-assessment number.")

    ids = list(scenario_ids_for_args(args))
    if not ids:
        raise SystemExit("Provide scenario IDs or use --all.")
    if args.all and args.count < 10:
        console.print("[red]The challenge requires at least 10 calls. Use --count 10 or more.[/red]")
        raise SystemExit(2)

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token) if not args.dry_run else None
    console.print(f"Target number is locked to [bold]{settings.assessment_number}[/bold].")
    console.print(f"Placing {len(ids)} call(s). Keep your Flask/ngrok server running in another terminal.")

    for index, scenario_id in enumerate(ids, start=1):
        create_outbound_call(client, scenario_id, dry_run=args.dry_run)
        if index < len(ids):
            console.print(f"Waiting {args.delay} seconds before next call...")
            time.sleep(args.delay)


if __name__ == "__main__":
    main()
