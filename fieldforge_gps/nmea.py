"""Bounded, checksum-required RMC/GGA subset, not a navigation certificate.

RMC establishes dated positions; GGA supplies diagnostics and negative fix status.
Two-digit RMC years use an explicit 1980..2079 window. Receiver datum MUST be
configured to WGS84 by the operator; these sentences do not establish the datum.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone

MAX_SENTENCE = 512  # Accommodate long vendor precision fields, but bound memory.
TALKERS = frozenset({"GP", "GN", "GL", "GA", "GB", "BD", "GQ", "GI"})
NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?\Z")
UTC_TIME = re.compile(r"([0-9]{2})([0-9]{2})([0-9]{2})(?:\.([0-9]{1,6}))?\Z")


class SentenceError(ValueError):
    """A short diagnostic that intentionally does not echo private input."""


@dataclass(frozen=True)
class Observation:
    family: str
    talker: str
    valid: bool
    reason: str
    seconds_utc: float | None = None
    timestamp: datetime | None = None
    latitude: float | None = None
    longitude: float | None = None
    speed_knots: float | None = None
    course_true: float | None = None
    satellites: int | None = None
    hdop: float | None = None
    quality: int | None = None


def _number(value: str, name: str, maximum: float, *, optional: bool = False):
    if not value and optional:
        return None
    if len(value) > 24 or not NUMBER.fullmatch(value):
        raise SentenceError(f"Invalid {name} field.")
    result = float(value)
    if not math.isfinite(result) or result > maximum:
        raise SentenceError(f"Out-of-range {name} field.")
    return result


def _time(value: str, *, optional: bool = False) -> float | None:
    if not value and optional:
        return None
    match = UTC_TIME.fullmatch(value)
    if not match:
        raise SentenceError("Invalid UTC time field.")
    hour, minute, second = (int(match[i]) for i in range(1, 4))
    # Fail closed at a leap second; never silently change the instant.
    if hour > 23 or minute > 59 or second > 59:
        raise SentenceError("UTC time out of range; leap seconds are not supported.")
    fraction = int((match[4] or "").ljust(6, "0")) / 1_000_000
    return hour * 3600 + minute * 60 + second + fraction


def _timestamp(date: str, seconds: float) -> datetime:
    if not re.fullmatch(r"[0-9]{6}", date):
        raise SentenceError("Invalid UTC date field.")
    day, month, year = int(date[:2]), int(date[2:4]), int(date[4:])
    year += 1900 if year >= 80 else 2000
    whole = int(seconds)
    try:
        return datetime(
            year,
            month,
            day,
            whole // 3600,
            whole // 60 % 60,
            whole % 60,
            round((seconds - whole) * 1_000_000),
            tzinfo=timezone.utc,
        )
    except ValueError as exc:
        raise SentenceError("Invalid calendar date or UTC time.") from exc


def _coordinate(value: str, hemisphere: str, *, latitude: bool) -> float:
    digits = 2 if latitude else 3
    if not re.fullmatch(rf"[0-9]{{{digits + 2}}}(?:\.[0-9]{{1,12}})?", value):
        raise SentenceError("Invalid degrees/minutes coordinate field.")
    if hemisphere not in (("N", "S") if latitude else ("E", "W")):
        raise SentenceError("Invalid coordinate hemisphere.")
    degrees, minutes = int(value[:digits]), float(value[digits:])
    maximum = 90 if latitude else 180
    if minutes >= 60 or degrees > maximum or (degrees == maximum and minutes != 0):
        raise SentenceError("Coordinate outside geographic bounds.")
    result = degrees + minutes / 60
    return -result if hemisphere in ("S", "W") else result


def parse_sentence(raw: bytes) -> Observation | None:
    """Parse one bounded ASCII sentence. Unsupported checksummed types return None."""
    if not isinstance(raw, bytes) or len(raw) > MAX_SENTENCE:
        raise SentenceError("Sentence is not bytes or exceeds the 512-byte limit.")
    if raw.endswith(b"\r\n"):
        raw = raw[:-2]
    elif raw.endswith(b"\n"):
        raw = raw[:-1]
    if not raw.startswith(b"$") or raw.count(b"*") != 1:
        raise SentenceError("Missing sentence delimiter or required checksum.")
    body, checksum = raw[1:].split(b"*", 1)
    if any(c < 32 or c > 126 for c in body) or not re.fullmatch(rb"[0-9A-Fa-f]{2}", checksum):
        raise SentenceError("Invalid ASCII data or checksum spelling.")
    expected = 0
    for value in body:
        expected ^= value
    if expected != int(checksum, 16):
        raise SentenceError("GPS sentence checksum mismatch.")
    fields = body.decode("ascii").split(",")
    header = fields[0]
    if not re.fullmatch(r"[A-Z]{5}", header):
        raise SentenceError("Unsupported sentence header.")
    talker, family = header[:2], header[2:]
    if family not in ("RMC", "GGA") or talker not in TALKERS:
        return None
    if family == "RMC":
        if not 12 <= len(fields) <= 14:
            raise SentenceError("Unsupported RMC field count.")
        if fields[2] not in ("A", "V"):
            raise SentenceError("Invalid RMC status.")
        seconds = _time(fields[1], optional=fields[2] == "V")
        stamp = _timestamp(fields[9], seconds) if fields[9] and seconds is not None else None
        mode = fields[12] if len(fields) >= 13 else ""
        nav = fields[13] if len(fields) >= 14 else ""
        # Conservative supported subset: vendor/unknown/estimated modes cannot
        # become a current position. Empty/absent legacy mode uses status A.
        if fields[2] == "V" or mode not in ("", "A", "D", "R", "F", "P") or nav not in ("", "S"):
            return Observation(
                family, talker, False, "RMC void or unsupported/estimated mode.", seconds, stamp
            )
        if stamp is None:
            raise SentenceError("A dated RMC position is required.")
        speed = _number(fields[7], "speed", 2000, optional=True)
        course = _number(fields[8], "course", 360, optional=True)
        if course == 360:
            course = 0.0
        return Observation(
            family,
            talker,
            True,
            "Receiver-reported RMC position.",
            seconds,
            stamp,
            _coordinate(fields[3], fields[4], latitude=True),
            _coordinate(fields[5], fields[6], latitude=False),
            speed,
            course,
        )
    if len(fields) != 15:
        raise SentenceError("Unsupported GGA field count.")
    if not re.fullmatch(r"[0-8]", fields[6]):
        raise SentenceError("Invalid GGA quality field.")
    quality = int(fields[6])
    seconds = _time(fields[1], optional=quality == 0)
    if quality not in (1, 2, 4, 5):
        return Observation(
            family,
            talker,
            False,
            "GGA no fix or unsupported/estimated quality.",
            seconds,
            quality=quality,
        )
    if not re.fullmatch(r"[0-9]{1,3}", fields[7]):
        raise SentenceError("Invalid satellite count.")
    satellites = int(fields[7])
    if not 1 <= satellites <= 199:
        raise SentenceError("Satellite count outside the supported range.")
    return Observation(
        family,
        talker,
        True,
        "GGA diagnostic; dated RMC still required.",
        seconds,
        latitude=_coordinate(fields[2], fields[3], latitude=True),
        longitude=_coordinate(fields[4], fields[5], latitude=False),
        satellites=satellites,
        hdop=_number(fields[8], "HDOP", 999, optional=True),
        quality=quality,
    )


class Framer:
    """Bounded newline framing. Never parse a suffix of an overlong record."""

    def __init__(self):
        self._buffer = bytearray()
        self._dropping = False

    def feed(self, chunk: bytes) -> list[bytes | None]:
        if not isinstance(chunk, bytes) or len(chunk) > 4096:
            raise ValueError("Feed at most 4096 bytes at a time.")
        result: list[bytes | None] = []
        for value in chunk:
            if self._dropping:
                if value == 10:
                    self._dropping = False
                continue
            self._buffer.append(value)
            if len(self._buffer) > MAX_SENTENCE:
                self._buffer.clear()
                self._dropping = value != 10
                result.append(None)
            elif value == 10:
                result.append(bytes(self._buffer))
                self._buffer.clear()
        return result

    def finish(self) -> list[bytes | None]:
        """An unterminated last record is rejected, not guessed complete."""
        pending = bool(self._buffer)
        self._buffer.clear()
        self._dropping = False
        return [None] if pending else []
