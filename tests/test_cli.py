import json

from fieldforge.cli import main


def _run(argv, capsys):
    assert main(argv) == 0
    return json.loads(capsys.readouterr().out)


def test_cli_builds_household_inventory_and_dashboard(tmp_path, capsys):
    db = tmp_path / "fieldforge.db"
    prefix = ["--database", str(db)]

    created_member = _run(prefix + ["add-member", "Alex", "--calories", "1900"], capsys)
    assert created_member["name"] == "Alex"

    created_water = _run(
        prefix
        + [
            "add-item",
            "Stored water",
            "water",
            "10",
            "gallon",
            "--liters-per-unit",
            "3.78541",
            "--minimum",
            "12",
        ],
        capsys,
    )
    assert created_water["category"] == "water"

    created_food = _run(
        prefix
        + [
            "add-item",
            "Meal packs",
            "food",
            "10",
            "pack",
            "--calories-per-unit",
            "1000",
        ],
        capsys,
    )
    assert created_food["category"] == "food"

    dashboard = _run(prefix + ["dashboard"], capsys)
    assert dashboard["household_members"] == 1
    assert dashboard["inventory_items"] == 2
    assert dashboard["water"]["days_remaining"] > 0
    assert dashboard["food"]["days_remaining"] > 0
    assert dashboard["alerts"]["low_stock"][0]["name"] == "Stored water"


def test_cli_scenario_and_power_tools(tmp_path, capsys):
    db = tmp_path / "fieldforge.db"
    prefix = ["--database", str(db)]
    scenario = _run(prefix + ["scenario", "evacuation"], capsys)
    assert scenario["scenario"] == "evacuation"
    assert scenario["actions"]

    battery = _run(prefix + ["battery-runtime", "1000", "100"], capsys)
    assert battery["runtime_hours"] > 7

    solar = _run(prefix + ["solar", "400", "5"], capsys)
    assert solar["daily_energy_wh"] == 1500.0
