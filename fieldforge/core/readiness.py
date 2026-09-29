"""Preparedness/readiness scoring with transparent weights."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReadinessScore:
    score: float
    grade: str
    components: dict[str, float]
    recommendations: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "grade": self.grade,
            "components": dict(self.components),
            "recommendations": list(self.recommendations),
        }


def _bounded_ratio(value: float, target: float) -> float:
    if target <= 0:
        raise ValueError("target must be positive")
    return max(0.0, min(float(value) / target, 1.0))


def readiness_score(
    *,
    water_days: float,
    food_days: float,
    backup_power_hours: float,
    go_bag_fraction: float,
    communications_fraction: float,
    evacuation_plan_fraction: float,
) -> ReadinessScore:
    """Calculate a conservative preparedness score from visible assumptions.

    Targets intentionally favor several days of basic resilience while avoiding
    any claim that a numeric score guarantees safety in a real emergency.
    """
    for name, value in (
        ("water_days", water_days),
        ("food_days", food_days),
        ("backup_power_hours", backup_power_hours),
    ):
        if value < 0:
            raise ValueError(f"{name} cannot be negative")
    for name, value in (
        ("go_bag_fraction", go_bag_fraction),
        ("communications_fraction", communications_fraction),
        ("evacuation_plan_fraction", evacuation_plan_fraction),
    ):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be between 0 and 1")

    components = {
        "water": 100.0 * _bounded_ratio(water_days, 7.0),
        "food": 100.0 * _bounded_ratio(food_days, 14.0),
        "power": 100.0 * _bounded_ratio(backup_power_hours, 24.0),
        "go_bag": 100.0 * go_bag_fraction,
        "communications": 100.0 * communications_fraction,
        "evacuation": 100.0 * evacuation_plan_fraction,
    }
    weights = {
        "water": 0.25,
        "food": 0.20,
        "power": 0.15,
        "go_bag": 0.15,
        "communications": 0.10,
        "evacuation": 0.15,
    }
    score = sum(components[name] * weights[name] for name in components)
    grade = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F"

    recommendations: list[str] = []
    if water_days < 3:
        recommendations.append("Increase immediately usable potable-water reserves.")
    elif water_days < 7:
        recommendations.append("Build water reserves toward the 7-day planning target.")
    if food_days < 7:
        recommendations.append("Increase shelf-stable food reserves and rotate them regularly.")
    if backup_power_hours < 8:
        recommendations.append("Improve backup power for critical loads or reduce emergency loads.")
    if go_bag_fraction < 0.8:
        recommendations.append("Complete and stage household go-bags.")
    if communications_fraction < 0.8:
        recommendations.append("Add redundant communication, charging, and contact methods.")
    if evacuation_plan_fraction < 0.8:
        recommendations.append("Complete destinations, routes, rendezvous points, and contact plans.")

    return ReadinessScore(round(score, 2), grade, components, tuple(recommendations))
