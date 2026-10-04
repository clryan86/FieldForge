"""Live-map policy and view geometry. No I/O, persistence, or inferred positions.

Call ``live_status`` with a NEW Session.snapshot() each time. Session is responsible
for receipt-age, UTC, duplicate-epoch and no-fix rejection. A saved Snapshot is not
an enduring authorization to show a live position.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .mbtiles import MAX_LAT
from .mercator import MercatorView
from .nmea import Observation
from .review_map import View, wrap
from .session import Snapshot

POLL_MS = 200
RECENTER_SECONDS = 1.0


@dataclass(frozen=True)
class LiveStatus:
    code: str
    message: str
    position: Observation | None = None


def live_status(
    snapshot: Snapshot | None, *, consent: bool, wgs84_confirmed: bool, mercator: bool = False
) -> LiveStatus:
    """Fail closed: only an opted-in, running serial Session can supply a marker.

    Do not infer accuracy from GGA/HDOP, use course as a compass heading, infer a
    location from a GPX track, or label serial source authenticity as verified.
    """
    if consent is not True:
        return LiveStatus(
            "off",
            "Live layer OFF. No position shown; showing a marker never starts trip recording.",
        )
    if wgs84_confirmed is not True:
        return LiveStatus(
            "datum", "Live position hidden. Confirm WGS84 in Receiver controls first."
        )
    if snapshot is None:
        return LiveStatus(
            "disconnected", "No receiver connected. Select a local GPS in Receiver controls."
        )
    if snapshot.mode != "serial":
        return LiveStatus(
            "recorded", "RECORDED FILE — NOT LIVE. File positions never enter the live map layer."
        )
    if snapshot.running is not True:
        return LiveStatus(
            "disconnected", "Receiver is not running. No live marker or automatic following."
        )
    point = snapshot.position
    if point is None:
        return LiveStatus(
            "no-fix", snapshot.status[:240] or "No accepted fresh receiver fix. Position hidden."
        )
    coordinates = (point.latitude, point.longitude)
    if (
        point.family != "RMC"
        or point.valid is not True
        or not isinstance(point.timestamp, datetime)
        or point.timestamp.tzinfo is None
        or point.timestamp.utcoffset() is None
        or any(type(v) not in (int, float) or not math.isfinite(v) for v in coordinates)
        or not -90 <= point.latitude <= 90
        or not -180 <= point.longitude <= 180
    ):
        return LiveStatus(
            "invalid", "Receiver position rejected. No complete dated coordinate is available."
        )
    if mercator and abs(point.latitude) > MAX_LAT:
        return LiveStatus(
            "polar",
            "Receiver is outside Web Mercator. Position is NOT moved to the map edge; use World overview.",
        )
    return LiveStatus(
        "fix", "Fresh serial fix — receiver-reported, not independently verified.", point
    )


def centered(view: View | MercatorView, point: Observation) -> View | MercatorView:
    """Recenter without changing scale or clamping polar fixes into Mercator."""
    lon = wrap(point.longitude)
    if isinstance(view, MercatorView):
        return MercatorView(lon, point.latitude, view.level)
    if isinstance(view, View):
        return View(lon, point.latitude, view.span)
    raise ValueError("Unsupported map view.")


def outside_follow_box(
    view: View | MercatorView, point: Observation, width: int, height: int
) -> bool:
    """Central half of viewport is a dead zone to avoid unnecessary tile reloads."""
    if any(type(v) is not int or v < 1 for v in (width, height)):
        raise ValueError("Map dimensions must be positive integers.")
    xy = view.position(point.longitude, point.latitude, width, height)
    return xy is None or not (
        width * 0.25 <= xy[0] <= width * 0.75 and height * 0.25 <= xy[1] <= height * 0.75
    )
