"""Go-bag and emergency-kit readiness helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KitItem:
    name: str
    category: str
    weight: float = 1.0
    critical: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.category.strip():
            raise ValueError("kit item name and category cannot be empty")
        if self.weight <= 0:
            raise ValueError("kit item weight must be positive")


@dataclass(frozen=True)
class KitAssessment:
    completion_fraction: float
    weighted_score: float
    missing: tuple[str, ...]
    missing_critical: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "completion_fraction": self.completion_fraction,
            "weighted_score": self.weighted_score,
            "missing": list(self.missing),
            "missing_critical": list(self.missing_critical),
        }


DEFAULT_GO_BAG: tuple[KitItem, ...] = (
    KitItem("water", "water", 3.0, True),
    KitItem("shelf-stable food", "food", 2.0, True),
    KitItem("essential medications", "medical", 4.0, True),
    KitItem("first-aid kit", "medical", 3.0, True),
    KitItem("flashlight", "lighting", 2.0, True),
    KitItem("spare batteries or power bank", "power", 2.0, True),
    KitItem("weather-appropriate clothing", "clothing", 2.0, True),
    KitItem("emergency contact card", "documents", 2.0, True),
    KitItem("identity/document copies", "documents", 2.0, False),
    KitItem("hygiene supplies", "hygiene", 1.0, False),
    KitItem("work gloves", "tools", 1.0, False),
    KitItem("whistle", "signaling", 1.0, False),
    KitItem("local map", "navigation", 1.0, False),
    KitItem("cash", "finance", 1.0, False),
)


def assess_kit(
    present_items: set[str],
    template: tuple[KitItem, ...] = DEFAULT_GO_BAG,
) -> KitAssessment:
    """Score a kit using normalized names and weighted critical items."""
    if not template:
        raise ValueError("template cannot be empty")
    normalized = {item.strip().lower() for item in present_items if item.strip()}
    total_weight = sum(item.weight for item in template)
    present_weight = 0.0
    missing: list[str] = []
    missing_critical: list[str] = []
    present_count = 0
    for item in template:
        if item.name.lower() in normalized:
            present_weight += item.weight
            present_count += 1
        else:
            missing.append(item.name)
            if item.critical:
                missing_critical.append(item.name)
    return KitAssessment(
        completion_fraction=present_count / len(template),
        weighted_score=100.0 * present_weight / total_weight,
        missing=tuple(missing),
        missing_critical=tuple(missing_critical),
    )
