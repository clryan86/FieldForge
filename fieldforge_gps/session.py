"""Local GPS sessions: no network transport, auto-connect or database access.

One session owns one worker and a bounded parser. GUI callers only take snapshots.
Stopping clears the position immediately; workers never touch Tk widgets.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import stat
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .nmea import Framer, Observation, SentenceError, parse_sentence
from .tracks import TrackPoint, TrackRecorder, TripSnapshot, TripSummary

STALE_SECONDS = 5.0
CLOCK_TOLERANCE_SECONDS = 10.0
MAX_RECORDING_BYTES = 8 * 1024 * 1024
BAUD_RATES = (4800, 9600, 19200, 38400, 57600, 115200)


@dataclass(frozen=True)
class Snapshot:
    mode: str
    status: str
    position: Observation | None
    accepted: int
    rejected: int
    ignored: int
    duplicates: int
    gga: Observation | None
    recording_sha256: str
    running: bool


class PositionState:
    """Synchronous state machine. Sessions serialize access using a lock."""

    def __init__(self, mode: str):
        if mode not in ("serial", "recorded"):
            raise ValueError("Choose serial or recorded mode.")
        self.mode = mode
        self.position: Observation | None = None
        self.gga: Observation | None = None
        self.highwater: datetime | None = None
        self.received = 0.0
        self.accepted = self.rejected = self.ignored = self.duplicates = 0
        self.status = "Waiting for a dated RMC position."

    def invalidate(self, reason: str):
        self.position = None
        self.status = reason

    def consume(self, raw: bytes | None, now: float):
        if not math.isfinite(now):
            raise ValueError("Receipt time must be finite.")
        try:
            if raw is None:
                raise SentenceError("Overlong or unterminated record rejected.")
            event = parse_sentence(raw)
        except SentenceError as exc:
            self.rejected += 1
            self.invalidate(str(exc))
            return
        if event is None:
            self.ignored += 1
            return
        self.accepted += 1
        if event.family == "GGA":
            self.gga = event
            if not event.valid:
                self.invalidate(event.reason)
            return
        if not event.valid:
            if event.timestamp is not None and (
                self.highwater is None or event.timestamp > self.highwater
            ):
                self.highwater = event.timestamp
            self.invalidate(event.reason)
            return
        # All valid RMC events have a timestamp. Never refresh freshness from a
        # repeated/backwards epoch, even after an error invalidates the fix.
        if self.highwater is not None and event.timestamp <= self.highwater:
            self.duplicates += 1
            if self.position is not None and event.timestamp == self.position.timestamp:
                if (event.latitude, event.longitude) != (
                    self.position.latitude,
                    self.position.longitude,
                ):
                    self.invalidate("Conflicting positions at the same receiver time.")
            return
        self.highwater = event.timestamp
        if self.gga is not None and not self.gga.valid and self.gga.seconds_utc is not None:
            delta = (event.seconds_utc - self.gga.seconds_utc) % 86400
            if not 0 < delta < 43200:
                self.invalidate("Waiting for RMC later than the GGA no-fix observation.")
                return
        self.position = event
        self.received = now
        self.status = (
            "Recorded position — NOT live."
            if self.mode == "recorded"
            else "Receiver-reported position."
        )

    def visible(self, now: float, wall: datetime) -> tuple[str, Observation | None]:
        if self.position is None:
            return self.status, None
        if self.mode == "recorded":
            return "Recorded position — NOT live.", self.position
        age = now - self.received
        if not math.isfinite(age) or age < 0 or age >= STALE_SECONDS:
            return "Stale receiver position — hidden; waiting for new data.", None
        if wall.tzinfo is None:
            raise ValueError("An aware system UTC time is required.")
        if abs((wall - self.position.timestamp).total_seconds()) > CLOCK_TOLERANCE_SECONDS:
            return "Receiver/system UTC mismatch — position hidden; check both clocks.", None
        return self.status, self.position


def validate_port(port: str, baud: int) -> tuple[str, int]:
    """Local serial devices only. In particular, no pySerial URL handlers."""
    if not isinstance(port, str) or not 1 <= len(port) <= 240 or any(ord(c) < 32 for c in port):
        raise ValueError("Enter a local GPS serial device.")
    if "://" in port or ".." in port or "\\" in port:
        raise ValueError("Network URLs and redirected paths are not accepted.")
    windows = re.fullmatch(r"COM[1-9][0-9]{0,4}", port, re.IGNORECASE)
    posix = re.fullmatch(r"/dev/(?:[A-Za-z0-9_.-]+|pts/[0-9]+)", port)
    if not windows and not posix:
        raise ValueError("Use a local device such as COM3 or /dev/ttyACM0.")
    if type(baud) is not int or baud not in BAUD_RATES:
        raise ValueError("Choose a supported baud rate matching your GPS receiver.")
    return port.upper() if windows else port, baud


def open_serial(port: str, baud: int):
    """Open a user-selected receiver; no application payload is ever written.

    Driver control-line transitions may still occur while opening a serial port.
    """
    port, baud = validate_port(port, baud)
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError(
            "Live serial input needs the optional pySerial package; see GPS_RECEIVER.md."
        ) from exc
    if not hasattr(serial, "Serial"):
        raise RuntimeError("The installed 'serial' module is not compatible pySerial.")
    stream = serial.Serial(
        port=None,
        baudrate=baud,
        timeout=0.2,
        write_timeout=0.2,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    )
    try:
        stream.dtr = False
        stream.rts = False
        stream.port = port
        stream.open()
        stream.reset_input_buffer()
        return stream
    except Exception:
        stream.close()
        raise


def _recording_stream(path: str | Path):
    """Reject nonregular sources without blocking on a pipe/device."""
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Choose an ordinary local NMEA recording, not a link, device or pipe.")
    if info.st_size > MAX_RECORDING_BYTES:
        raise ValueError("Recording exceeds the 8 MiB limit.")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        actual = os.fstat(fd)
        if not stat.S_ISREG(actual.st_mode) or actual.st_size > MAX_RECORDING_BYTES:
            raise ValueError("Recording changed or is not a supported regular file.")
        if (actual.st_dev, actual.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("Recording changed while opening; choose it again.")
        return os.fdopen(fd, "rb"), actual
    except Exception:
        os.close(fd)
        raise


class Session:
    def __init__(
        self,
        mode: str,
        *,
        clock: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] | None = None,
    ):
        self.state = PositionState(mode)
        self._clock = clock
        self._utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._framer = Framer()
        self._thread: threading.Thread | None = None
        self._running = False
        self._started = False
        self._digest = ""
        self._trip = TrackRecorder(mode)
        self._collect_recorded = False

    def _consume_locked(self, line):
        now = self._clock()
        before = self.state.position
        if self._trip.state == "recording" and self.state.mode == "serial":
            _, visible = self.state.visible(now, self._utc_now())
            if visible is None:
                self._trip.gap()
        self.state.consume(line, now)
        if self._trip.state != "recording":
            return
        status, point = self.state.visible(now, self._utc_now())
        if point is None:
            self._trip.gap()
        elif point is not before:
            self._trip.append(TrackPoint(point.latitude, point.longitude, point.timestamp), now)

    def _feed(self, data: bytes):
        with self._lock:
            if self._stop.is_set():
                return
            for line in self._framer.feed(data):
                self._consume_locked(line)

    def _error(self, message: str):
        with self._lock:
            if not self._stop.is_set():
                self.state.invalidate(message)
                self._digest = ""
                if self._collect_recorded:
                    self._trip.fail_recording()
                else:
                    self._trip.finish(
                        "Serial input interrupted; trip capture stopped. Export retained points explicitly."
                    )

    def _launch(self, target):
        with self._lock:
            if self._started or self._stop.is_set():
                raise RuntimeError("Create a new session for each connection or recording.")
            self._started = self._running = True
        self._thread = threading.Thread(target=target, name="fieldforge-gps", daemon=True)
        self._thread.start()

    def start_serial(
        self, port: str, baud: int, *, wgs84_confirmed: bool, opener: Callable = open_serial
    ):
        if self.state.mode != "serial" or wgs84_confirmed is not True:
            raise ValueError("Confirm that the selected GPS receiver is configured to WGS84.")
        port, baud = validate_port(port, baud)

        def run():
            stream = None
            try:
                stream = opener(port, baud)
                while not self._stop.is_set():
                    data = stream.read(1024)
                    if data:
                        self._feed(data)
                    else:
                        self._stop.wait(0.01)
            except Exception:
                # Do not echo OS errors containing private paths/device IDs.
                self._error(
                    "Serial input unavailable or disconnected. Check the device and pySerial installation."
                )
            finally:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
                with self._lock:
                    self._running = False

        self._launch(run)

    def start_recording(
        self,
        path: str | Path,
        *,
        collect_track: bool = False,
        wgs84_confirmed: bool = False,
        consent: bool = False,
    ):
        if self.state.mode != "recorded":
            raise ValueError("Recordings require recorded mode.")
        if type(collect_track) is not bool:
            raise ValueError("Choose whether to inspect a recorded track explicitly.")
        if collect_track:
            with self._lock:
                if self._started or self._stop.is_set():
                    raise RuntimeError("Create a new session for each recording.")
                self._trip.start(consent=consent, wgs84_confirmed=wgs84_confirmed)
                self._collect_recorded = True

        def run():
            try:
                digest = hashlib.sha256()
                stream, before = _recording_stream(path)
                with stream:
                    total = 0
                    while not self._stop.is_set():
                        data = stream.read(4096)
                        if not data:
                            break
                        total += len(data)
                        if total > MAX_RECORDING_BYTES:
                            raise ValueError("Recording exceeds the 8 MiB limit.")
                        digest.update(data)
                        self._feed(data)
                    after = os.fstat(stream.fileno())
                    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                        after.st_size,
                        after.st_mtime_ns,
                        after.st_ctime_ns,
                    ) or total != before.st_size:
                        raise ValueError("Recording changed while reading.")
                with self._lock:
                    if not self._stop.is_set():
                        for line in self._framer.finish():
                            self._consume_locked(line)
                        self._digest = digest.hexdigest()
                        if self._collect_recorded:
                            self._trip.seal_recording(self._digest)
            except Exception:
                self._error(
                    "Recording rejected, changed or unreadable. Use a regular NMEA file of at most 8 MiB."
                )
            finally:
                with self._lock:
                    self._running = False

        self._launch(run)

    def start_trip(self, *, consent: bool, wgs84_confirmed: bool) -> None:
        with self._lock:
            if self.state.mode != "serial" or not self._running or self._stop.is_set():
                raise ValueError("Connect a local serial receiver before starting a trip.")
            self._trip.start(consent=consent, wgs84_confirmed=wgs84_confirmed)

    def pause_trip(self) -> None:
        with self._lock:
            self._trip.pause()

    def resume_trip(self, *, consent: bool, wgs84_confirmed: bool) -> None:
        with self._lock:
            if not self._running or self._stop.is_set():
                raise ValueError("The original receiver connection is no longer active.")
            self._trip.resume(consent=consent, wgs84_confirmed=wgs84_confirmed)

    def finish_trip(self) -> None:
        with self._lock:
            if self.state.mode != "serial":
                raise ValueError("A recorded file must finish validation before use.")
            self._trip.finish()

    def discard_trip(self) -> None:
        with self._lock:
            if self.state.mode == "recorded" and self._running:
                raise ValueError("Disconnect the recorded-file reader before discarding.")
            self._trip.discard()
            self._collect_recorded = False

    def trip_summary(self) -> TripSummary:
        with self._lock:
            if self._trip.state == "recording" and self.state.mode == "serial":
                _, visible = self.state.visible(self._clock(), self._utc_now())
                if visible is None:
                    self._trip.gap()
            return self._trip.summary()

    def trip_snapshot(self) -> TripSnapshot:
        with self._lock:
            return self._trip.snapshot()

    def snapshot(self) -> Snapshot:
        with self._lock:
            status, position = self.state.visible(self._clock(), self._utc_now())
            # A partially read recording is never offered for export or map use.
            if self.state.mode == "recorded" and self._running:
                status, position = "Reading local recording — NOT live.", None
            return Snapshot(
                self.state.mode,
                status,
                position,
                self.state.accepted,
                self.state.rejected,
                self.state.ignored,
                self.state.duplicates,
                self.state.gga,
                self._digest,
                self._running,
            )

    def stop(self):
        self._stop.set()
        with self._lock:
            self.state.invalidate("Disconnected; no current position.")
            self.state.gga = None
            self._digest = ""
            if self._collect_recorded and not self._trip.summary().source_sha256:
                self._trip.fail_recording()
            else:
                self._trip.finish(
                    "Disconnected; trip capture stopped. Retained history is NOT a current position."
                )

    def wait(self, timeout: float = 1.0) -> bool:
        """For tests/CLI only; the GUI never joins a worker on its event thread."""
        if self._thread is not None:
            self._thread.join(timeout)
            return not self._thread.is_alive()
        return True
