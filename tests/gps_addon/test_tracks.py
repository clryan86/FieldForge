from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from fieldforge_gps.tracks import TrackPoint, TrackRecorder, distance_m, validate_point

WALL = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)


def point(second=0, lat=10.0, lon=20.0):
    return TrackPoint(lat, lon, WALL + timedelta(seconds=second))


def recorder(source="serial", limit=50000):
    result = TrackRecorder(source, limit=limit)
    result.start(consent=True, wgs84_confirmed=True)
    return result


def test_idle_has_no_history_and_does_not_capture():
    r = TrackRecorder("serial")
    assert not r.append(point(), 0)
    assert r.summary().state == "idle"
    assert r.summary().point_count == 0 and not r.snapshot().segments


@pytest.mark.parametrize(
    "consent,wgs", [(False, True), (True, False), (1, True), (True, 1), (None, True)]
)
def test_explicit_boolean_permissions_required(consent, wgs):
    r = TrackRecorder("serial")
    with pytest.raises(ValueError):
        r.start(consent=consent, wgs84_confirmed=wgs)
    assert r.summary().state == "idle"


@pytest.mark.parametrize("limit", [0, -1, 50001, True, 2.5, "50"])
def test_capacity_validation(limit):
    with pytest.raises(ValueError):
        TrackRecorder("serial", limit=limit)


def test_unknown_source():
    with pytest.raises(ValueError):
        TrackRecorder("internet")


@pytest.mark.parametrize(
    "field,value",
    [
        ("latitude", 91),
        ("longitude", -181),
        ("latitude", float("nan")),
        ("longitude", float("inf")),
        ("latitude", True),
        ("longitude", "20"),
        ("timestamp", WALL.replace(tzinfo=None)),
        ("timestamp", WALL.astimezone(timezone(timedelta(hours=2)))),
        ("timestamp", "2026-10-02"),
    ],
)
def test_invalid_track_points(field, value):
    with pytest.raises(ValueError):
        validate_point(replace(point(), **{field: value}))


def test_extreme_coordinate_validation_and_spherical_distance():
    validate_point(point(lat=90, lon=180))
    validate_point(point(lat=-90, lon=-180))
    assert distance_m(point(lat=0, lon=0), point(lat=0, lon=1)) == pytest.approx(
        111194.9266, abs=0.001
    )
    assert distance_m(point(), point()) == 0
    assert distance_m(point(lat=0, lon=179.9), point(lat=0, lon=-179.9)) == pytest.approx(
        22238.9853, abs=0.001
    )


def test_summary_counts_distance_and_frozen_snapshot():
    r = recorder()
    r.append(point(), 0)
    r.append(point(1, lon=20.001), 1)
    frozen = r.snapshot()
    assert frozen.summary.point_count == 2 and frozen.summary.segment_count == 1
    assert frozen.summary.distance_m > 100
    assert frozen.summary.first_utc == WALL
    assert frozen.summary.last_utc == WALL + timedelta(seconds=1)
    r.append(point(2), 2)
    assert len(frozen.segments[0]) == 2
    assert r.summary().point_count == 3
    with pytest.raises(ValueError):
        r.start(consent=True, wgs84_confirmed=True)


@pytest.mark.parametrize(
    "second,receipt,segments", [(4.999, 4.999, 1), (5, 4, 2), (4, 5, 2), (1, -1, 2)]
)
def test_gap_boundaries(second, receipt, segments):
    r = recorder()
    r.append(point(), 0)
    r.append(point(second, lon=21), receipt)
    assert r.summary().segment_count == segments
    assert (r.summary().distance_m == 0) == (segments == 2)


def test_pause_resume_does_not_capture_or_connect_gap():
    r = recorder()
    r.append(point(), 0)
    r.pause()
    assert not r.append(point(1, lon=22), 1)
    with pytest.raises(ValueError):
        r.resume(consent=False, wgs84_confirmed=True)
    r.resume(consent=True, wgs84_confirmed=True)
    r.append(point(2, lon=23), 2)
    assert [len(s) for s in r.snapshot().segments] == [1, 1]
    assert r.summary().distance_m == 0


def test_repeated_gaps_do_not_make_empty_segments():
    r = recorder()
    r.gap()
    r.append(point(), 0)
    r.gap()
    revision = r.summary().revision
    r.gap()
    assert r.summary().revision == revision
    r.append(point(1), 1)
    assert [len(s) for s in r.snapshot().segments] == [1, 1]


def test_nonadvancing_timestamps_are_omitted():
    r = recorder()
    r.append(point(2), 0)
    assert not r.append(point(2), 1)
    assert not r.append(point(1), 2)
    r.append(point(3), 3)
    assert r.summary().point_count == 2 and r.summary().segment_count == 2


@pytest.mark.parametrize("receipt", [float("nan"), float("inf"), "now", True])
def test_bad_receipt_time(receipt):
    r = recorder()
    with pytest.raises(ValueError):
        r.append(point(), receipt)
    assert r.summary().point_count == 0


def test_limit_stops_without_overwriting_old_points_and_discard_restarts():
    r = recorder(limit=2)
    r.append(point(), 0)
    r.append(point(1), 1)
    assert r.summary().state == "finished"
    assert "limit" in r.summary().reason
    assert not r.append(point(2), 2)
    with pytest.raises(ValueError):
        r.resume(consent=True, wgs84_confirmed=True)
    old = r.snapshot()
    r.discard()
    assert not r.snapshot().segments and r.summary().point_count == 0
    assert old.summary.point_count == 2
    r.start(consent=True, wgs84_confirmed=True)
    r.append(point(3), 3)
    assert r.summary().point_count == 1


def test_recorded_data_is_hidden_until_entire_source_validated():
    r = recorder("recorded")
    r.append(point(), 0)
    r.append(point(1), 100)  # Wall and receipt time don't establish recorded-file freshness.
    assert r.summary().state == "reading" and r.summary().point_count == 0
    assert not r.snapshot().segments
    r.seal_recording("a" * 64)
    assert r.summary().point_count == 2 and r.summary().segment_count == 1
    assert r.summary().state == "finished" and r.summary().source_sha256 == "a" * 64


@pytest.mark.parametrize("digest", ["", "A" * 64, "z" * 64, "a" * 63])
def test_bad_recorded_fingerprint(digest):
    r = recorder("recorded")
    r.append(point(), 0)
    with pytest.raises(ValueError):
        r.seal_recording(digest)
    assert not r.snapshot().segments


def test_failed_recording_clears_partial_data():
    r = recorder("recorded")
    r.append(point(), 0)
    r.fail_recording()
    assert r.summary().state == "failed"
    assert not r.snapshot().segments and r.summary().point_count == 0
    assert r.summary().source_sha256 == ""


def test_capped_recorded_file_stays_hidden_until_sealed():
    r = recorder("recorded", limit=1)
    r.append(point(), 0)
    assert r.summary().state == "reading"
    r.seal_recording("b" * 64)
    assert r.summary().point_count == 1 and "limit" in r.summary().reason
