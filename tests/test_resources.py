import pytest

from fieldforge.core.models import HouseholdMember, InventoryCategory, InventoryItem
from fieldforge.planners.kits import DEFAULT_GO_BAG, assess_kit
from fieldforge.planners.resources import (
    battery_runtime_hours,
    food_runway,
    generator_runtime_hours,
    solar_daily_energy_wh,
    water_runway,
)


def _members():
    return [
        HouseholdMember("A", daily_water_liters=3.78541, daily_calories=2000),
        HouseholdMember("B", daily_water_liters=3.78541, daily_calories=2000),
    ]


def test_water_and_food_runway_use_inventory_and_reserve():
    inventory = [
        InventoryItem("Water jugs", InventoryCategory.WATER, 10, "gallon", liters_per_unit=3.78541),
        InventoryItem("Meal packs", InventoryCategory.FOOD, 20, "pack", calories_per_unit=1000),
    ]
    assert water_runway(_members(), inventory).days_remaining == pytest.approx(4.5)
    assert food_runway(_members(), inventory).days_remaining == pytest.approx(4.5)


def test_power_calculators_expose_derating_assumptions():
    assert battery_runtime_hours(1000, 100) == pytest.approx(7.65)
    assert generator_runtime_hours(10, 1) == pytest.approx(8.5)
    assert solar_daily_energy_wh(400, 5) == pytest.approx(1500)


def test_invalid_resource_inputs_are_rejected():
    with pytest.raises(ValueError):
        battery_runtime_hours(1000, 0)
    with pytest.raises(ValueError):
        generator_runtime_hours(10, -1)
    with pytest.raises(ValueError):
        solar_daily_energy_wh(-1, 4)


def test_go_bag_assessment_weights_critical_items():
    present = {item.name for item in DEFAULT_GO_BAG if item.critical}
    assessment = assess_kit(present)
    assert assessment.completion_fraction < 1.0
    assert assessment.weighted_score > 50.0
    assert assessment.missing
    assert not assessment.missing_critical
