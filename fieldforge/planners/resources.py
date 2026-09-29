"""Offline resource planning calculators."""

from __future__ import annotations

from dataclasses import dataclass

from fieldforge.core.models import HouseholdMember, InventoryCategory, InventoryItem


@dataclass(frozen=True)
class ResourceRunway:
    available: float
    daily_need: float
    days_remaining: float | None
    unit: str

    def as_dict(self) -> dict[str, float | str | None]:
        return {
            "available": self.available,
            "daily_need": self.daily_need,
            "days_remaining": self.days_remaining,
            "unit": self.unit,
        }


def water_runway(
    members: list[HouseholdMember],
    inventory: list[InventoryItem],
    *,
    reserve_fraction: float = 0.10,
) -> ResourceRunway:
    """Estimate potable-water runway using explicit household assumptions."""
    if not 0.0 <= reserve_fraction < 1.0:
        raise ValueError("reserve_fraction must be between 0 and 1")
    available = sum(
        item.quantity * item.liters_per_unit
        for item in inventory
        if item.category is InventoryCategory.WATER
    )
    usable = available * (1.0 - reserve_fraction)
    daily_need = sum(member.daily_water_liters for member in members)
    days = usable / daily_need if daily_need > 0 else None
    return ResourceRunway(usable, daily_need, days, "liters")


def food_runway(
    members: list[HouseholdMember],
    inventory: list[InventoryItem],
    *,
    reserve_fraction: float = 0.10,
) -> ResourceRunway:
    """Estimate calorie runway from locally stored inventory."""
    if not 0.0 <= reserve_fraction < 1.0:
        raise ValueError("reserve_fraction must be between 0 and 1")
    available = sum(
        item.quantity * item.calories_per_unit
        for item in inventory
        if item.category is InventoryCategory.FOOD
    )
    usable = available * (1.0 - reserve_fraction)
    daily_need = float(sum(member.daily_calories for member in members))
    days = usable / daily_need if daily_need > 0 else None
    return ResourceRunway(usable, daily_need, days, "kcal")


def battery_runtime_hours(
    battery_watt_hours: float,
    load_watts: float,
    *,
    usable_fraction: float = 0.85,
    inverter_efficiency: float = 0.90,
) -> float:
    """Estimate battery runtime with visible derating assumptions."""
    if battery_watt_hours < 0 or load_watts <= 0:
        raise ValueError("battery_watt_hours must be non-negative and load_watts positive")
    if not 0.0 < usable_fraction <= 1.0:
        raise ValueError("usable_fraction must be in (0, 1]")
    if not 0.0 < inverter_efficiency <= 1.0:
        raise ValueError("inverter_efficiency must be in (0, 1]")
    return battery_watt_hours * usable_fraction * inverter_efficiency / load_watts


def generator_runtime_hours(
    fuel_available: float,
    consumption_per_hour: float,
    *,
    reserve_fraction: float = 0.15,
) -> float:
    """Estimate generator runtime in the caller's chosen fuel units."""
    if fuel_available < 0 or consumption_per_hour <= 0:
        raise ValueError("fuel_available must be non-negative and consumption_per_hour positive")
    if not 0.0 <= reserve_fraction < 1.0:
        raise ValueError("reserve_fraction must be between 0 and 1")
    return fuel_available * (1.0 - reserve_fraction) / consumption_per_hour


def solar_daily_energy_wh(
    panel_watts: float,
    peak_sun_hours: float,
    *,
    system_efficiency: float = 0.75,
) -> float:
    """Estimate daily solar harvest using a conservative efficiency factor."""
    if panel_watts < 0 or peak_sun_hours < 0:
        raise ValueError("panel_watts and peak_sun_hours cannot be negative")
    if not 0.0 < system_efficiency <= 1.0:
        raise ValueError("system_efficiency must be in (0, 1]")
    return panel_watts * peak_sun_hours * system_efficiency
