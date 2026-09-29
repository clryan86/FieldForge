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


def test_cli_scenario_power_navigation_incident_and_evacuation_tools(tmp_path, capsys):
    db = tmp_path / "fieldforge.db"
    prefix = ["--database", str(db)]
    _run(prefix + ["add-member", "A"], capsys)
    _run(prefix + ["add-member", "B"], capsys)

    scenario = _run(prefix + ["scenario", "evacuation"], capsys)
    assert scenario["scenario"] == "evacuation"
    assert scenario["actions"]

    battery = _run(prefix + ["battery-runtime", "1000", "100"], capsys)
    assert battery["runtime_hours"] > 7

    solar = _run(prefix + ["solar", "400", "5"], capsys)
    assert solar["daily_energy_wh"] == 1500.0

    waypoint = _run(
        prefix + ["waypoint-add", "Meetup", "39.5", "-75.5", "--kind", "rendezvous"],
        capsys,
    )
    assert waypoint["kind"] == "rendezvous"
    waypoints = _run(prefix + ["waypoints", "--kind", "rendezvous"], capsys)
    assert waypoints[0]["name"] == "Meetup"

    incident = _run(prefix + ["incident-add", "warning", "Fuel below target"], capsys)
    assert incident["status"] == "recorded"
    incidents = _run(prefix + ["incidents"], capsys)
    assert incidents[0]["severity"] == "warning"

    evacuation = _run(
        prefix
        + [
            "evacuation-check",
            "SUV",
            "5",
            "500",
            "Family meetup",
            "120",
            "--destination-confirmed",
        ],
        capsys,
    )
    assert evacuation["feasible"] is True
    assert evacuation["seat_margin"] == 3
