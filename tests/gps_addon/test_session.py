import hashlib
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from fieldforge_gps.session import PositionState, Session, validate_port

from .test_nmea import gga, rmc, sentence

WALL = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)


def test_valid_and_stale():
    state = PositionState("serial")
    state.consume(rmc(), 100)
    assert state.visible(104.999, WALL)[1]
    assert state.visible(105, WALL)[1] is None
    assert state.visible(99, WALL)[1] is None


def test_wall_clock_mismatch_hidden():
    state = PositionState("serial")
    state.consume(rmc(), 100)
    assert state.visible(100, WALL + timedelta(seconds=11))[1] is None
    assert state.visible(100, WALL - timedelta(seconds=11))[1] is None
    with pytest.raises(ValueError):
        state.visible(100, WALL.replace(tzinfo=None))


def test_duplicates_never_refresh():
    s = PositionState("serial")
    s.consume(rmc(), 0)
    s.consume(rmc(), 4)
    assert s.visible(5, WALL)[1] is None
    assert s.duplicates == 1


def test_old_timestamps_never_replace():
    s = PositionState("serial")
    s.consume(rmc(time="120001"), 0)
    s.consume(rmc(time="120000", lat="1100.0"), 1)
    assert s.position.latitude == 10
    assert s.position.timestamp.second == 1


def test_same_epoch_conflict_and_recovery():
    s = PositionState("serial")
    s.consume(rmc(), 0)
    s.consume(rmc(lat="1100.0"), 1)
    assert s.position is None
    s.consume(rmc(), 2)
    assert s.position is None
    s.consume(rmc(time="120001"), 3)
    assert s.position


@pytest.mark.parametrize(
    "invalid", [rmc(status="V"), rmc(mode="E"), b"bad\n", gga(quality="0"), gga(quality="6")]
)
def test_negative_observation_immediately_clears(invalid):
    s = PositionState("serial")
    s.consume(rmc(), 0)
    s.consume(invalid, 1)
    assert s.position is None
    s.consume(rmc(), 2)
    assert s.position is None
    s.consume(rmc(time="120001"), 3)
    assert s.position


def test_gga_only_does_not_establish_position():
    s = PositionState("serial")
    s.consume(gga(), 0)
    assert s.position is None


def test_gga_no_fix_same_epoch_cannot_be_overridden():
    s = PositionState("serial")
    s.consume(gga(quality="0", time="120002"), 0)
    s.consume(rmc(time="120001"), 1)
    assert s.position is None
    s.consume(rmc(time="120002"), 2)
    assert s.position is None
    s.consume(rmc(time="120003"), 3)
    assert s.position


def test_gga_invalid_midnight_and_next_day():
    s = PositionState("serial")
    s.consume(gga(quality="0", time="235959"), 0)
    s.consume(rmc(time="000000", date="031026"), 1)
    assert s.position


def test_unsupported_sentence_does_not_refresh():
    s = PositionState("serial")
    s.consume(rmc(), 0)
    s.consume(sentence("GPGSV,1,1,0"), 4)
    assert s.ignored == 1
    assert s.visible(5, WALL)[1] is None


def test_recorded_never_called_live_and_not_clock_limited():
    s = PositionState("recorded")
    s.consume(rmc(date="010180"), 0)
    status, p = s.visible(999999, WALL)
    assert "NOT live" in status and p.timestamp.year == 1980


@pytest.mark.parametrize(
    "port",
    [
        "socket://host:123",
        "rfc2217://localhost:1",
        "loop://",
        "http://x",
        "\\\\server\\COM1",
        "/dev/../tmp/file",
        "relative",
        "/tmp/gps",
        "COM0",
        "COM1\n",
    ],
)
def test_unsafe_ports_refused(port):
    with pytest.raises(ValueError):
        validate_port(port, 9600)


@pytest.mark.parametrize(
    "port", ["COM1", "com22", "/dev/ttyUSB0", "/dev/ttyACM0", "/dev/cu.usbmodem123", "/dev/pts/2"]
)
def test_local_port_names(port):
    assert validate_port(port, 9600)[1] == 9600


@pytest.mark.parametrize("baud", [True, 0, -1, 9600.0, "9600", 921600])
def test_baud_validation(baud):
    with pytest.raises(ValueError):
        validate_port("COM1", baud)


def test_recording_streaming_and_fingerprint(tmp_path):
    p = tmp_path / "private.nmea"
    raw = rmc() + gga() + rmc(time="120001")
    p.write_bytes(raw)
    s = Session("recorded")
    s.start_recording(p)
    assert s.wait(2)
    shot = s.snapshot()
    assert shot.mode == "recorded" and "NOT live" in shot.status
    assert shot.position.timestamp.second == 1
    assert shot.recording_sha256 == hashlib.sha256(raw).hexdigest()
    assert p.read_bytes() == raw
    assert sorted(x.name for x in tmp_path.iterdir()) == ["private.nmea"]
    s.stop()
    assert s.snapshot().position is None
    assert not s.snapshot().recording_sha256


@pytest.mark.parametrize(
    "kind", ["oversize", "symlink", "fifo", "directory", "truncated", "no-such-file"]
)
def test_recording_invalid(tmp_path, kind):
    path = tmp_path / "bad.nmea"
    if kind == "oversize":
        with path.open("wb") as f:
            f.truncate(8 * 1024 * 1024 + 1)
    elif kind == "symlink":
        source = tmp_path / "source"
        source.write_bytes(rmc())
        path.symlink_to(source)
    elif kind == "fifo":
        if not hasattr(os, "mkfifo"):
            pytest.skip("POSIX FIFO test")
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    elif kind == "truncated":
        path.write_bytes(rmc()[:-2])
    s = Session("recorded")
    s.start_recording(path)
    assert s.wait(2)
    assert s.snapshot().position is None


class FakeReceiver:
    def __init__(self):
        self.chunks = [rmc()[:20], rmc()[20:]]
        self.closed = False
        self.reads = 0

    def read(self, n):
        assert n <= 1024
        self.reads += 1
        time.sleep(0.005)
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        self.closed = True


def test_serial_worker_partial_data_stop_and_no_writes():
    r = FakeReceiver()  # No write method: sending payloads would fail this test.
    s = Session("serial", utc_now=lambda: WALL)
    s.start_serial("COM3", 9600, wgs84_confirmed=True, opener=lambda *_: r)
    deadline = time.monotonic() + 2
    while s.snapshot().position is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert s.snapshot().position
    s.stop()
    assert s.snapshot().position is None
    assert s.wait(1) and r.closed
    assert not s.snapshot().running


def test_opener_cannot_start_without_datum_confirmation():
    s = Session("serial")
    with pytest.raises(ValueError):
        s.start_serial("COM1", 9600, wgs84_confirmed=False, opener=lambda *_: pytest.fail("opened"))


def test_worker_device_failure_clears_and_closes():
    class Failed(FakeReceiver):
        def read(self, n):
            raise OSError("private-device-path")

    r = Failed()
    s = Session("serial")
    s.start_serial("COM3", 9600, wgs84_confirmed=True, opener=lambda *_: r)
    assert s.wait(1) and r.closed
    snap = s.snapshot()
    assert snap.position is None and "private" not in snap.status


def test_stopping_before_slow_open_finishes_discards_data():
    gate = threading.Event()
    r = FakeReceiver()

    def opener(*args):
        gate.wait(1)
        return r

    s = Session("serial")
    s.start_serial("COM1", 9600, wgs84_confirmed=True, opener=opener)
    s.stop()
    gate.set()
    assert s.wait(2) and r.closed and r.reads == 0
    assert s.snapshot().position is None


def test_sessions_cannot_restart(tmp_path):
    p = tmp_path / "sample"
    p.write_bytes(rmc())
    s = Session("recorded")
    s.start_recording(p)
    assert s.wait(1)
    with pytest.raises(RuntimeError):
        s.start_recording(p)
