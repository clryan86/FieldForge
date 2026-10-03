"""Bounded, opt-in, memory-only trip history. No files, sockets or device access.

The owning Session serializes all mutations. Frozen snapshots can cross into UI
and export code. A path is receiver evidence, never a navigable route. No line
or distance is added across rejected data, pauses or observed time gaps.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

MAX_TRIP_POINTS = 50_000
GAP_SECONDS = 5.0
EARTH_RADIUS_M = 6_371_000.0  # Deliberately approximate spherical geometry.


@dataclass(frozen=True)
class TrackPoint:
    latitude: float
    longitude: float
    timestamp: datetime


def validate_point(point: TrackPoint) -> None:
    if not isinstance(point, TrackPoint):
        raise ValueError("Expected a dated track point.")
    for value, bound in ((point.latitude, 90), (point.longitude, 180)):
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not -bound <= value <= bound
        ):
            raise ValueError("Track coordinates must be finite WGS84 decimal degrees.")
    stamp = point.timestamp
    if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
        raise ValueError("Track points require an aware UTC timestamp.")


def distance_m(a: TrackPoint, b: TrackPoint) -> float:
    """Approximate great-circle separation; not road length or measured travel."""
    p, q = math.radians(a.latitude), math.radians(b.latitude)
    dl = math.radians((b.longitude - a.longitude + 180) % 360 - 180)
    value = math.sin((q - p) / 2) ** 2 + math.cos(p) * math.cos(q) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(max(0.0, min(1.0, value))))


@dataclass(frozen=True)
class TripSummary:
    source: str
    state: str
    reason: str
    point_count: int
    segment_count: int
    distance_m: float
    first_utc: datetime | None
    last_utc: datetime | None
    revision: int
    limit: int
    source_sha256: str


@dataclass(frozen=True)
class TripSnapshot:
    summary: TripSummary
    segments: tuple[tuple[TrackPoint, ...], ...]


class TrackRecorder:
    """Synchronous recorder; caller must hold its Session lock.

    Serial history is absent until start(). File history is invisible until the
    entire input is checked and seal_recording() supplies its fingerprint.
    """

    def __init__(self, source: str, *, limit: int = MAX_TRIP_POINTS):
        if source not in ("serial", "recorded"):
            raise ValueError("Unknown trip source.")
        if type(limit) is not int or not 1 <= limit <= MAX_TRIP_POINTS:
            raise ValueError("Trip point limit must be between 1 and 50,000.")
        self.source = source
        self.limit = limit
        self.state = "idle"
        self.reason = "No trip requested. Nothing is being recorded."
        self._segments: list[list[TrackPoint]] = []
        self._count = 0
        self._distance = 0.0
        self._break = True
        self._receipt: float | None = None
        self._last: TrackPoint | None = None
        self._revision = 0
        self._sha256 = ""
        self._sealed = source == "serial"

    def start(self, *, consent: bool, wgs84_confirmed: bool) -> None:
        if consent is not True or wgs84_confirmed is not True:
            raise ValueError("Confirm WGS84 and consent to private, in-memory trip history.")
        if self.state != "idle":
            raise ValueError("Discard the previous trip before starting another.")
        self.state = "recording"
        self.reason = "Waiting for the next accepted dated position."
        self._revision += 1

    def gap(
        self, reason: str = "Position data interrupted; next point starts a new segment."
    ) -> None:
        if self.state == "recording" and not self._break:
            self._break = True
            self.reason = reason
            self._revision += 1

    def append(self, point: TrackPoint, receipt: float) -> bool:
        if self.state != "recording":
            return False
        validate_point(point)
        if type(receipt) not in (int, float) or not math.isfinite(receipt):
            raise ValueError("Receipt time must be finite.")
        if self._last is not None:
            delta = (point.timestamp - self._last.timestamp).total_seconds()
            if delta <= 0:
                self.gap("Repeated or backward receiver time; point omitted.")
                return False
            if delta >= GAP_SECONDS:
                self.gap("Receiver timestamp gap; next point starts a new segment.")
            if self.source == "serial" and self._receipt is not None:
                elapsed = receipt - self._receipt
                if elapsed < 0 or elapsed >= GAP_SECONDS:
                    self.gap("Reception time gap; next point starts a new segment.")
        if self._break:
            self._segments.append([])
            self._break = False
        elif self._last is not None:
            self._distance += distance_m(self._last, point)
        self._segments[-1].append(point)
        self._last = point
        self._receipt = receipt
        self._count += 1
        self.reason = "Capturing accepted points in memory only."
        self._revision += 1
        if self._count == self.limit:
            self.finish(
                "Point limit reached; capture stopped. Export this partial trip before continuing."
            )
        return True

    def pause(self) -> None:
        if self.source != "serial" or self.state != "recording":
            raise ValueError("Only an active serial trip can be paused.")
        self.gap()
        self.state = "paused"
        self.reason = "Paused. Incoming positions are not added to this trip."
        self._revision += 1

    def resume(self, *, consent: bool, wgs84_confirmed: bool) -> None:
        if self.source != "serial" or self.state != "paused":
            raise ValueError("Only a paused serial trip can be resumed.")
        if consent is not True or wgs84_confirmed is not True:
            raise ValueError("Confirm WGS84 and consent before resuming trip history.")
        self.state = "recording"
        self._break = True
        self.reason = "Resumed; waiting for a new position in a new segment."
        self._revision += 1

    def finish(
        self, reason: str = "Finished. Trip remains in memory until export or discard."
    ) -> None:
        if self.state in ("recording", "paused"):
            self.state = "finished"
            self._break = True
            self.reason = reason
            self._revision += 1

    def seal_recording(self, sha256: str) -> None:
        if self.source != "recorded" or not re.fullmatch(r"[a-f0-9]{64}", sha256):
            raise ValueError("A recorded trip needs a complete source fingerprint.")
        if self.state not in ("recording", "finished"):
            raise ValueError("No recorded trip is awaiting validation.")
        self.finish("Recorded path inspected; NOT LIVE. Kept in memory until export or discard.")
        self._sha256 = sha256
        self._sealed = True
        self._revision += 1

    def discard(self) -> None:
        """Drop Python references; this is not secure memory/OS-swap erasure."""
        self._segments.clear()
        self._count = 0
        self._distance = 0.0
        self._last = None
        self._receipt = None
        self._break = True
        self._sha256 = ""
        self._sealed = self.source == "serial"
        self.state = "idle"
        self.reason = "Trip discarded from this workspace. Exported files are unchanged."
        self._revision += 1

    def fail_recording(self) -> None:
        self.discard()
        self.state = "failed"
        self.reason = "Recorded path rejected; all partial track data discarded."

    def summary(self) -> TripSummary:
        hidden = (
            self.source == "recorded" and not self._sealed and self.state not in ("idle", "failed")
        )
        return TripSummary(
            self.source,
            "reading" if hidden else self.state,
            "Reading and validating recorded input — NOT LIVE." if hidden else self.reason,
            0 if hidden else self._count,
            0 if hidden else len(self._segments),
            0.0 if hidden else self._distance,
            self._segments[0][0].timestamp if not hidden and self._count else None,
            self._last.timestamp if not hidden and self._last else None,
            self._revision,
            self.limit,
            self._sha256,
        )

    def snapshot(self) -> TripSnapshot:
        summary = self.summary()
        segments = () if summary.state == "reading" else tuple(tuple(s) for s in self._segments)
        return TripSnapshot(summary, segments)
