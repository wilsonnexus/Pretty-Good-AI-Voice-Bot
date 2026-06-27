from __future__ import annotations

from .scenarios import SCENARIOS


def main() -> None:
    print("Loaded scenarios:")
    for scenario in SCENARIOS[:10]:
        print(f"- {scenario.id}: {scenario.title}")
    print("\nNow run: python -m pgai_voice_bot.web")


if __name__ == "__main__":
    main()
