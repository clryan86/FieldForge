"""Evacuation feasibility and rendezvous planning."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VehiclePlan:
    name: str
    seats_available: int
    estimated_range_km: float
    readiness_fraction: float = 1.0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("vehicle name cannot be empty")
        if self.seats_available < 0 or self.estimated_range_km < 0:
            raise ValueError("seats and range cannot be negative")
        if not 0.0 <= self.readiness_fraction <= 1.0:
            raise ValueError("readiness_fraction must be between 0 and 1")


@dataclass(frozen=True)
class DestinationPlan:
    name: str
    distance_km: float
    confirmed_available: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("destination name cannot be empty")
        if self.distance_km < 0:
            raise ValueError("distance_km cannot be negative")


@dataclass(frozen=True)
class EvacuationAssessment:
    feasible: bool
    seat_margin: int
    range_margin_km: float
    score: float
    recommendations: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "feasible": self.feasible,
            "seat_margin": self.seat_margin,
            "range_margin_km": self.range_margin_km,
            "score": self.score,
            "recommendations": list(self.recommendations),
        }


def assess_evacuation(
    household_count: int,
    vehicle: VehiclePlan,
    destination: DestinationPlan,
    *,
    range_reserve_fraction: float = 0.20,
) -> EvacuationAssessment:
    """Assess whether one planned vehicle can reach one planned destination."""
    if household_count < 0:
        raise ValueError("household_count cannot be negative")
    if not 0.0 <= range_reserve_fraction < 1.0:
        raise ValueError("range_reserve_fraction must be between 0 and 1")

    seat_margin = vehicle.seats_available - household_count
    usable_range = vehicle.estimated_range_km * (1.0 - range_reserve_fraction)
    range_margin = usable_range - destination.distance_km
    seat_ok = seat_margin >= 0
    range_ok = range_margin >= 0
    destination_ok = destination.confirmed_available

    score = 0.0
    score += 35.0 if seat_ok else max(0.0, 35.0 + seat_margin * 10.0)
    score += 35.0 if range_ok else max(0.0, 35.0 + range_margin)
    score += 20.0 * vehicle.readiness_fraction
    score += 10.0 if destination_ok else 0.0

    recommendations: list[str] = []
    if not seat_ok:
        recommendations.append("Add transport capacity or assign additional vehicles.")
    if not range_ok:
        recommendations.append("Increase usable fuel/range or select a closer destination.")
    if vehicle.readiness_fraction < 0.8:
        recommendations.append("Raise vehicle readiness: fuel, tires, fluids, charging, and emergency kit.")
    if not destination_ok:
        recommendations.append("Confirm the destination is available before relying on it.")
    recommendations.append("Maintain an alternate destination and route independent of the primary plan.")

    return EvacuationAssessment(
        feasible=seat_ok and range_ok and destination_ok,
        seat_margin=seat_margin,
        range_margin_km=round(range_margin, 3),
        score=round(min(score, 100.0), 2),
        recommendations=tuple(recommendations),
    )
