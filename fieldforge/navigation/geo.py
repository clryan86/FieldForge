"""Offline navigation math for waypoints and rendezvous planning."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

_EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True)
class Waypoint:
    name: str
    latitude: float
    longitude: float
    kind: str = "waypoint"
    notes: str = ""
    id: int | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("waypoint name cannot be empty")
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError("latitude must be between -90 and 90")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError("longitude must be between -180 and 180")
        if not self.kind.strip():
            raise ValueError("waypoint kind cannot be empty")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def distance_m(a: Waypoint, b: Waypoint) -> float:
    """Great-circle distance using the haversine formula."""
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(b.longitude - a.longitude)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2.0 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def initial_bearing_degrees(a: Waypoint, b: Waypoint) -> float:
    """Initial true bearing from waypoint a to b in degrees [0, 360)."""
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlon = math.radians(b.longitude - a.longitude)
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def pace_count(distance_meters: float, meters_per_pace: float) -> float:
    if distance_meters < 0 or meters_per_pace <= 0:
        raise ValueError("distance must be non-negative and meters_per_pace positive")
    return distance_meters / meters_per_pace
