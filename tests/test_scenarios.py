from pgai_voice_bot.scenarios import SCENARIOS, get_scenario


def test_at_least_ten_scenarios():
    assert len(SCENARIOS) >= 10


def test_scenario_ids_unique():
    ids = [s.id for s in SCENARIOS]
    assert len(ids) == len(set(ids))


def test_get_scenario():
    scenario = get_scenario("06_office_hours_weekend")
    assert "Sunday" in scenario.goal
