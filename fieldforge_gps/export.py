"""Explicit one-waypoint GPX export. Never modifies a FieldForge database."""

from __future__ import annotations

import math
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .session import Snapshot

NS = "http://www.topografix.com/GPX/1/1"


def format_longitude(value: float) -> str:
    """Keep rounded output inside GPX's [-180, 180) longitude interval."""
    text = f"{value:.10f}"
    return "-180.0000000000" if float(text) == 180.0 else text


def waypoint_bytes(snapshot: Snapshot, name: str, *, wgs84_confirmed: bool) -> bytes:
    if wgs84_confirmed is not True:
        raise ValueError("Confirm WGS84 receiver/source datum before GPX export.")
    if snapshot.running and snapshot.mode == "recorded":
        raise ValueError("Finish reading the recording before export.")
    point = snapshot.position
    if point is None or not point.valid or point.family != "RMC" or point.timestamp is None:
        raise ValueError("No accepted dated RMC position is available.")
    if point.timestamp.tzinfo is None or point.timestamp.utcoffset().total_seconds() != 0:
        raise ValueError("An aware UTC receiver timestamp is required.")
    if snapshot.mode == "recorded" and not re.fullmatch(r"[a-f0-9]{64}", snapshot.recording_sha256):
        raise ValueError("The recorded source fingerprint is missing.")
    for value, limit in ((point.latitude, 90), (point.longitude, 180)):
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not -limit <= value <= limit
        ):
            raise ValueError("Invalid position coordinate.")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        raise ValueError("Use a waypoint name of 1–120 characters.")
    if any(
        ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF or ord(c) in (0xFFFE, 0xFFFF)
        for c in name
    ):
        raise ValueError("Waypoint name contains unsupported characters.")
    if snapshot.mode not in ("serial", "recorded"):
        raise ValueError("Unknown position source.")
    # Literal namespace attribute avoids modifying ElementTree's global registry.
    root = ET.Element("gpx", {"xmlns": NS, "version": "1.1", "creator": "FieldForge GPS"})
    wpt = ET.SubElement(
        root, "wpt", {"lat": f"{point.latitude:.10f}", "lon": format_longitude(point.longitude)}
    )
    ET.SubElement(wpt, "time").text = point.timestamp.isoformat().replace("+00:00", "Z")
    label = "RECORDED — " if snapshot.mode == "recorded" else ""
    ET.SubElement(wpt, "name").text = label + name.strip()
    description = (
        "Recorded NMEA position; NOT live. "
        if snapshot.mode == "recorded"
        else "Receiver-reported NMEA position captured by the user. "
    )
    description += "Receiver UTC: " + point.timestamp.isoformat() + ". "
    description += (
        "Not independently verified; no route, destination safety or accuracy guarantee. "
        "Source datum confirmed as WGS84 by the user. RMC years interpreted as 1980–2079."
    )
    if snapshot.mode == "recorded":
        description += " Source SHA-256: " + snapshot.recording_sha256
    ET.SubElement(wpt, "desc").text = description
    ET.SubElement(wpt, "src").text = (
        "Local NMEA recording" if snapshot.mode == "recorded" else "Local serial GPS receiver"
    )
    ET.SubElement(wpt, "type").text = (
        "recorded-gps" if snapshot.mode == "recorded" else "receiver-gps"
    )
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def export_waypoint(path: str | Path, snapshot: Snapshot, name: str, *, wgs84_confirmed: bool):
    """Publish a complete new file atomically. Existing files/links are never replaced.

    Requires same-filesystem hard-link support. Unsupported filesystems fail
    explicitly rather than falling back to an overwrite or partial target.
    """
    data = waypoint_bytes(snapshot, name, wgs84_confirmed=wgs84_confirmed)
    target = Path(path)
    fd, temp = tempfile.mkstemp(prefix=".fieldforge-gps-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, target)
    finally:
        os.unlink(temp)
