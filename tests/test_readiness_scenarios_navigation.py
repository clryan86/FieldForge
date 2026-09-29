import pytest

from fieldforge.core.readiness import readiness_score
from fieldforge.navigation.geo import Waypoint, distance_m, initial_bearing_degrees, pace_count
from fieldforge.planners.evacuation import (
    DestinationPlan,
    VehiclePlan,
    assess_evacuation,
)
from fieldforge.scenarios.engine import available_scenarios, scenario_actions


def test_readiness_score_rewards_complete_preparation():
    result = readiness_score(
        water_days=7,
        food_days=14,
        backup_power_hours=24,
        go_bag_fraction=1.0,
        communications_fraction=1.0,
        evacuation_plan_fraction=1.0,
    )
    assert result.score == 100.0
    assert result.grade == "A"
    assert result.recommendations == ()


def test_readiness_score_identifies_major_gaps():
    result = readiness_score(
        water_days=1,
        food_days=2,
        backup_power_hours=0,
        go_bag_fraction=0.2,
        communications_fraction=0.0,
        evacuation_plan_fraction=0.0,
    )
    assert result.grade == "F"
    assert len(result.recommendations) >= 5


def test_scenarios_have_prioritized_actions():
    assert "power_outage" in available_scenarios()
    actions = scenario_actions("power-outage")
    assert actions
    assert any(action.priority.value == "critical" for action in actions)
    with pytest.raises(ValueError):
        scenario_actions("meteor-zombies")


def test_navigation_distance_bearing_and_pace_count():
    a = Waypoint("A", 0.0, 0.0)
    north = Waypoint("North", 1.0, 0.0)
    assert distance_m(a, north) == pytest.approx(111_195, rel=0.002)
    assert initial_bearing_degrees(a, north) == pytest.approx(0.0, abs=1e-9)
    assert pace_count(1000, 0.75) == pytest.approx(1333.333333, rel=1e-6)


def test_invalid_waypoints_are_rejected():
    with pytest.raises(ValueError):
        Waypoint("bad", 91.0, 0.0)
    with pytest.raises(ValueError):
        Waypoint("bad", 0.0, 181.0)


def test_evacuation_assessment_reports_transport_and_range_margin():
    vehicle = VehiclePlan("SUV", seats_available=5, estimated_range_km=500, readiness_fraction=0.9)
    destination = DestinationPlan("Family meetup", distance_km=160, confirmed_available=True)
    result = assess_evacuation(4, vehicle, destination)
    assert result.feasible is True
    assert result.seat_margin == 1
    assert result.range_margin_km == pytest.approx(240.0)
    assert result.score >= 90


def test_evacuation_assessment_flags_unconfirmed_or_unreachable_plan():
    vehicle = VehiclePlan("Car", seats_available=2, estimated_range_km=100, readiness_fraction=0.5)
    destination = DestinationPlan("Far shelter", distance_km=120, confirmed_available=False)
    result = assess_evacuation(4, vehicle, destination)
    assert result.feasible is False
    assert result.seat_margin < 0
    assert result.range_margin_km < 0
    assert len(result.recommendations) >= 3
