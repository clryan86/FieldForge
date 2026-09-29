"""Core domain models for FieldForge."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from enum import Enum
from typing import Any


class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class InventoryCategory(str, Enum):
    WATER = "water"
    FOOD = "food"
    MEDICAL = "medical"
    POWER = "power"
    FUEL = "fuel"
    TOOL = "tool"
    HYGIENE = "hygiene"
    CLOTHING = "clothing"
    COMMUNICATION = "communication"
    DOCUMENT = "document"
    OTHER = "other"


@dataclass(frozen=True)
class HouseholdMember:
    name: str
    daily_water_liters: float = 3.78541
    daily_calories: int = 2000
    notes: str = ""
    is_child: bool = False
    is_pet: bool = False
    id: int | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("member name cannot be empty")
        if self.daily_water_liters <= 0:
            raise ValueError("daily_water_liters must be positive")
        if self.daily_calories < 0:
            raise ValueError("daily_calories cannot be negative")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InventoryItem:
    name: str
    category: InventoryCategory
    quantity: float
    unit: str
    calories_per_unit: float = 0.0
    liters_per_unit: float = 0.0
    watt_hours_per_unit: float = 0.0
    expires_on: date | None = None
    minimum_quantity: float = 0.0
    location: str = ""
    notes: str = ""
    id: int | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("inventory item name cannot be empty")
        if self.quantity < 0:
            raise ValueError("quantity cannot be negative")
        if not self.unit.strip():
            raise ValueError("unit cannot be empty")
        for name, value in (
            ("calories_per_unit", self.calories_per_unit),
            ("liters_per_unit", self.liters_per_unit),
            ("watt_hours_per_unit", self.watt_hours_per_unit),
            ("minimum_quantity", self.minimum_quantity),
        ):
            if value < 0:
                raise ValueError(f"{name} cannot be negative")

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["category"] = self.category.value
        payload["expires_on"] = self.expires_on.isoformat() if self.expires_on else None
        return payload


@dataclass(frozen=True)
class EmergencyAction:
    title: str
    priority: Priority
    reason: str
    completed: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["priority"] = self.priority.value
        return payload
