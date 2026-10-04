import hashlib
import queue
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from fieldforge_gps.session import Session
from fieldforge_gps.track_export import track_bytes
from fieldforge_gps.tracks import TrackRecorder

from .test_nmea import gga, rmc, sentence
from .test_session import WALL


class FakeDevice:
    def __init__(self):
        self.messages = queue.Queue()
        self.closed = False

    def read(self, size):
        try:
            message = self.messages.get(timeout=0.03)
        except queue.Empty:
            return b""
        if isinstance(message, Exception):
            raise message
        return message

    def close(self):
        self.closed = True


def until(predicate, timeout=2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.003)
    assert predicate(), "timed out waiting for the injected receiver worker"


@pytest.fixture
def serial_session():
    device = FakeDevice()
    clock = [0.0]
    session = Session(
        "serial", clock=lambda: clock[0], utc_now=lambda: WALL + timedelta(seconds=clock[0])
    )
    session.start_serial("COM3", 9600, wgs84_confirmed=True, opener=lambda *args: device)
    yield session, device, clock
    session.stop()
    assert session.wait(2)
    assert device.closed


def request(session):
    session.start_trip(consent=True, wgs84_confirmed=True)


def load(path, collect=True):
    s = Session("recorded")
    s.start_recording(path, collect_track=collect, consent=True, wgs84_confirmed=True)
    assert s.wait(2)
    return s


def test_default_serial_retains_no_track_and_start_does_not_copy_old_fix(serial_session):
    s, device, clock = serial_session
    device.messages.put(rmc())
    until(lambda: s.snapshot().accepted == 1)
    assert s.trip_summary().point_count == 0
    request(s)
    assert s.trip_summary().point_count == 0
    device.messages.put(sentence("GPGSV,1,1,0"))
    until(lambda: s.snapshot().ignored == 1)
    assert s.trip_summary().point_count == 0
    clock[0] = 1
    device.messages.put(rmc(time="120001"))
    until(lambda: s.trip_summary().point_count == 1)
    assert s.trip_snapshot().segments[0][0].timestamp.second == 1


def test_every_accepted_epoch_captured_in_one_read_without_gui_polling(serial_session):
    s, device, clock = serial_session
    request(s)
    device.messages.put(rmc() + rmc(time="120001") + rmc(time="120002"))
    until(lambda: s.snapshot().accepted == 3)
    assert s.trip_summary().point_count == 3 and s.trip_summary().segment_count == 1


@pytest.mark.parametrize("bad", [b"bad\n", rmc(status="V"), gga(quality="0"), rmc(mode="E")])
def test_invalid_data_within_one_read_breaks_history(bad, serial_session):
    s, device, clock = serial_session
    request(s)
    device.messages.put(rmc() + bad + rmc(time="120001", lat="1000.1000"))
    until(lambda: s.trip_summary().point_count == 2)
    assert [len(segment) for segment in s.trip_snapshot().segments] == [1, 1]
    assert s.trip_summary().distance_m == 0


def test_duplicate_epoch_not_added_or_used_to_refresh_trip(serial_session):
    s, device, clock = serial_session
    request(s)
    device.messages.put(rmc() + rmc() + rmc(time="120001"))
    until(lambda: s.snapshot().duplicates == 1)
    assert s.trip_summary().point_count == 2 and s.trip_summary().segment_count == 1


def test_pause_receives_but_does_not_record_resume_starts_segment(serial_session):
    s, device, clock = serial_session
    request(s)
    device.messages.put(rmc())
    until(lambda: s.trip_summary().point_count == 1)
    s.pause_trip()
    clock[0] = 1
    device.messages.put(rmc(time="120001"))
    until(lambda: s.snapshot().accepted == 2)
    assert s.trip_summary().point_count == 1
    s.resume_trip(consent=True, wgs84_confirmed=True)
    clock[0] = 2
    device.messages.put(rmc(time="120002"))
    until(lambda: s.trip_summary().point_count == 2)
    assert s.trip_summary().segment_count == 2


def test_observed_staleness_without_bad_sentence_breaks_path(serial_session):
    s, device, clock = serial_session
    request(s)
    device.messages.put(rmc())
    until(lambda: s.trip_summary().point_count == 1)
    clock[0] = 5
    assert s.snapshot().position is None
    device.messages.put(rmc(time="120001"))
    until(lambda: s.trip_summary().point_count == 2)
    assert s.trip_summary().segment_count == 2


def test_clock_mismatched_live_epoch_never_captured(serial_session):
    s, device, clock = serial_session
    request(s)
    device.messages.put(rmc(time="120020"))
    until(lambda: s.snapshot().accepted == 1)
    assert s.snapshot().position is None and s.trip_summary().point_count == 0
    clock[0] = 21
    device.messages.put(rmc(time="120021"))
    until(lambda: s.trip_summary().point_count == 1)


def test_worker_failure_stops_capture_keeps_explicit_history(serial_session):
    s, device, clock = serial_session
    request(s)
    device.messages.put(rmc())
    until(lambda: s.trip_summary().point_count == 1)
    device.messages.put(OSError("private device information must not leak"))
    assert s.wait(2)
    assert s.snapshot().position is None
    t = s.trip_snapshot()
    assert t.summary.state == "finished" and t.summary.point_count == 1
    assert "private device" not in t.summary.reason
    assert b"private device" not in track_bytes(t, "trip", wgs84_confirmed=True)
    with pytest.raises(ValueError):
        s.resume_trip(consent=True, wgs84_confirmed=True)


def test_stop_clears_fix_but_retains_history_and_blocks_future_input(serial_session):
    s, device, clock = serial_session
    request(s)
    device.messages.put(rmc())
    until(lambda: s.trip_summary().point_count == 1)
    s.stop()
    s._feed(rmc(time="120001"))
    assert s.snapshot().position is None
    assert s.trip_summary().point_count == 1 and s.trip_summary().state == "finished"


def test_start_requires_active_serial_connection():
    for source in ("serial", "recorded"):
        s = Session(source)
        with pytest.raises(ValueError):
            request(s)
        assert not s.trip_snapshot().segments


def test_explicit_recorded_path_hash_and_segments_without_touching_source(tmp_path):
    source = tmp_path / "archive.nmea"
    raw = rmc() + rmc(time="120001") + b"bad\n" + rmc(time="120002") + rmc(time="120010")
    source.write_bytes(raw)
    s = load(source)
    trip = s.trip_snapshot()
    assert trip.summary.state == "finished"
    assert [len(segment) for segment in trip.segments] == [2, 1, 1]
    assert trip.summary.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert trip.summary.point_count == 4 and source.read_bytes() == raw
    s.stop()
    assert s.snapshot().position is None
    assert s.trip_summary().point_count == 4 and s.trip_summary().source_sha256
    assert b"NOT LIVE" in track_bytes(s.trip_snapshot(), "archive", wgs84_confirmed=True)


def test_normal_recording_inspection_does_not_implicitly_retain_path(tmp_path):
    source = tmp_path / "file.nmea"
    source.write_bytes(rmc() + rmc(time="120001"))
    s = load(source, collect=False)
    assert s.snapshot().position is not None
    assert s.trip_summary().state == "idle" and s.trip_summary().point_count == 0


def test_partial_recording_is_invisible_and_cancel_discards_it(tmp_path):
    source = tmp_path / "file.nmea"
    source.write_bytes(rmc() + rmc(time="120001"))
    s = Session("recorded")
    entered, release = threading.Event(), threading.Event()
    feed = s._feed

    def gated(data):
        feed(data)
        entered.set()
        release.wait(2)

    s._feed = gated
    try:
        s.start_recording(source, collect_track=True, consent=True, wgs84_confirmed=True)
        assert entered.wait(1)
        assert s.trip_summary().state == "reading" and not s.trip_snapshot().segments
        with pytest.raises(ValueError):
            track_bytes(s.trip_snapshot(), "partial", wgs84_confirmed=True)
        s.stop()
    finally:
        release.set()
        assert s.wait(2)
    assert s.trip_summary().state == "failed" and not s.trip_snapshot().segments


def test_changing_recorded_file_drops_all_partial_history(tmp_path):
    source = tmp_path / "file.nmea"
    source.write_bytes(rmc())
    s = Session("recorded")
    feed = s._feed

    def changed(data):
        feed(data)
        with source.open("ab") as stream:
            stream.write(b"changed\n")

    s._feed = changed

    # Only modify once so the test cannot produce an endlessly growing source.
    def once(data):
        changed(data)
        s._feed = feed

    s._feed = once
    s.start_recording(source, collect_track=True, consent=True, wgs84_confirmed=True)
    assert s.wait(2)
    assert s.trip_summary().state == "failed" and not s.trip_snapshot().segments


def test_missing_or_symlink_recording_leaves_no_track(tmp_path):
    for path in (tmp_path / "missing.nmea", tmp_path / "link.nmea"):
        if path.name.startswith("link"):
            path.symlink_to(tmp_path / "missing.nmea")
        s = load(path)
        assert s.trip_summary().state == "failed" and not s.trip_snapshot().segments


def test_bundled_original_fictional_example_is_complete_and_segmented():
    import fieldforge_gps

    source = Path(fieldforge_gps.__file__).parent / "data/SYNTHETIC-TRIP.nmea"
    s = load(source)
    assert s.trip_summary().point_count == 30
    assert [len(seg) for seg in s.trip_snapshot().segments] == [10, 10, 10]
    assert s.snapshot().rejected == 1


def test_point_limit_in_session_is_hard_stop_not_rolling_history(serial_session):
    s, device, clock = serial_session
    s._trip = TrackRecorder("serial", limit=2)
    request(s)
    device.messages.put(rmc() + rmc(time="120001") + rmc(time="120002"))
    until(lambda: s.snapshot().accepted == 3)
    assert s.trip_summary().point_count == 2 and s.trip_summary().state == "finished"
    assert s.trip_summary().last_utc.second == 1
