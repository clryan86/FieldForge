"""Explicit GPX 1.1 track export; no overwrite, implicit save or route conversion."""

from __future__ import annotations

import math
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .export import NS, format_longitude
from .tracks import MAX_TRIP_POINTS, TripSnapshot, validate_point


def track_bytes(trip: TripSnapshot, name: str, *, wgs84_confirmed: bool) -> bytes:
    if wgs84_confirmed is not True:
        raise ValueError("Confirm the source uses WGS84 before track export.")
    if not isinstance(trip, TripSnapshot):
        raise ValueError("Expected a frozen trip snapshot.")
    summary = trip.summary
    if summary.state not in ("paused", "finished"):
        raise ValueError(
            "Pause or finish the trip before exporting; file reads must finish validation."
        )
    if summary.source not in ("serial", "recorded"):
        raise ValueError("Unknown track source.")
    if summary.source == "recorded" and not re.fullmatch(r"[a-f0-9]{64}", summary.source_sha256):
        raise ValueError("A recorded track requires a validated source fingerprint.")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        raise ValueError("Use a trip name of 1–120 characters.")
    if any(
        ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF or ord(c) in (0xFFFE, 0xFFFF)
        for c in name
    ):
        raise ValueError("Trip name contains unsupported characters.")
    if not trip.segments or len(trip.segments) != summary.segment_count:
        raise ValueError("The trip has no usable segments or its segment count is inconsistent.")
    total = sum(len(segment) for segment in trip.segments)
    if total != summary.point_count or not 1 <= total <= MAX_TRIP_POINTS:
        raise ValueError("The trip point count is empty, inconsistent or over the limit.")
    last = None
    for segment in trip.segments:
        if not segment:
            raise ValueError("Empty track segments cannot be exported.")
        for point in segment:
            validate_point(point)
            if last is not None and point.timestamp <= last:
                raise ValueError("Receiver times must advance throughout a trip.")
            last = point.timestamp
    if (summary.first_utc, summary.last_utc) != (trip.segments[0][0].timestamp, last):
        raise ValueError("Trip time summary does not match the captured points.")
    if not math.isfinite(summary.distance_m) or summary.distance_m < 0:
        raise ValueError("Invalid approximate distance summary.")
    root = ET.Element("gpx", {"xmlns": NS, "version": "1.1", "creator": "FieldForge GPS Trips 0.2"})
    track = ET.SubElement(root, "trk")
    prefix = "RECORDED — NOT LIVE — " if summary.source == "recorded" else "CAPTURED HISTORY — "
    ET.SubElement(track, "name").text = prefix + name.strip()
    description = (
        "Historical receiver-reported points; NOT a current location or navigable route. "
        "Source datum asserted WGS84 by the user. No accuracy, road snapping or safe-passage guarantee. "
        "Separate segments preserve detected interruptions; no points are interpolated. "
        "RMC years interpreted as 1980–2079. "
        f"Capture state: {summary.state}. Point limit: {summary.limit}. "
    )
    # Reason is not arbitrary external text: keep metadata deterministic, bounded
    # and free of source filenames, local ports or operating-system error text.
    if summary.point_count == summary.limit:
        description += "POINT LIMIT REACHED — this may be a partial trip. "
    if summary.source == "recorded":
        description += "Recorded NMEA source; NOT LIVE. Source SHA-256: " + summary.source_sha256
    ET.SubElement(track, "desc").text = description
    ET.SubElement(track, "src").text = (
        "Local NMEA recording" if summary.source == "recorded" else "Explicit local serial capture"
    )
    ET.SubElement(track, "type").text = (
        "recorded-nmea-history" if summary.source == "recorded" else "captured-gps-history"
    )
    for segment in trip.segments:
        node = ET.SubElement(track, "trkseg")
        for point in segment:
            element = ET.SubElement(
                node,
                "trkpt",
                {"lat": f"{point.latitude:.10f}", "lon": format_longitude(point.longitude)},
            )
            ET.SubElement(element, "time").text = point.timestamp.isoformat().replace("+00:00", "Z")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def export_track(path: str | Path, trip: TripSnapshot, name: str, *, wgs84_confirmed: bool) -> None:
    """Atomic new-name publication on filesystems with hard-link support.

    Existing targets (including symlinks) are not replaced. There is no unsafe
    fallback on FAT/exFAT or other filesystems without hard links. This is not a
    power-loss durability or encryption guarantee. Use a trusted local folder.
    """
    data = track_bytes(trip, name, wgs84_confirmed=wgs84_confirmed)
    target = Path(path)
    fd, temp = tempfile.mkstemp(prefix=".fieldforge-trip-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, target)
    finally:
        os.unlink(temp)
