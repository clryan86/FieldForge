import os
import xml.etree.ElementTree as ET
from dataclasses import replace

import pytest

from fieldforge_gps.track_export import export_track, track_bytes

from .test_tracks import point, recorder

NS = {"g": "http://www.topografix.com/GPX/1/1"}


def trip(source="serial"):
    r = recorder(source)
    r.append(point(), 0)
    r.append(point(1, lon=20.001), 1)
    r.gap()
    r.append(point(2, lon=20.002), 2)
    if source == "recorded":
        r.seal_recording("a" * 64)
    else:
        r.finish()
    return r.snapshot()


def test_track_namespace_points_times_and_separate_segments():
    raw = track_bytes(trip(), "Private <trip> & no commands", wgs84_confirmed=True)
    root = ET.fromstring(raw)
    assert root.attrib["version"] == "1.1"
    assert len(root.findall("g:trk/g:trkseg", NS)) == 2
    assert len(root.findall("g:trk/g:trkseg/g:trkpt", NS)) == 3
    assert not root.findall("g:rte", NS) and not root.findall("g:wpt", NS)
    assert "<trip> & no commands" in root.findtext("g:trk/g:name", namespaces=NS)
    assert all(
        p.findtext("g:time", namespaces=NS).endswith("Z")
        for p in root.findall("g:trk/g:trkseg/g:trkpt", NS)
    )
    assert b"&lt;trip&gt;" in raw and b"/mnt/data" not in raw and b"COM3" not in raw


def test_recorded_label_and_fingerprint():
    raw = track_bytes(trip("recorded"), "Archive", wgs84_confirmed=True)
    assert b"RECORDED" in raw and b"NOT LIVE" in raw and b"a" * 64 in raw


@pytest.mark.parametrize(
    "name", ["", "  ", "x" * 121, "a\x00b", "a\nb", "\ud800", "\ufffe", "\x7f"]
)
def test_invalid_names(name):
    with pytest.raises(ValueError):
        track_bytes(trip(), name, wgs84_confirmed=True)


@pytest.mark.parametrize("state", ["idle", "recording", "reading", "failed"])
def test_unready_history_cannot_export(state):
    t = trip()
    with pytest.raises(ValueError):
        track_bytes(
            replace(t, summary=replace(t.summary, state=state)), "test", wgs84_confirmed=True
        )


def test_datum_and_recorded_provenance_gated():
    with pytest.raises(ValueError):
        track_bytes(trip(), "test", wgs84_confirmed=False)
    t = trip("recorded")
    with pytest.raises(ValueError):
        track_bytes(
            replace(t, summary=replace(t.summary, source_sha256="")), "test", wgs84_confirmed=True
        )


@pytest.mark.parametrize(
    "fields",
    [
        {"point_count": 4},
        {"segment_count": 0},
        {"first_utc": None},
        {"last_utc": None},
        {"distance_m": float("inf")},
        {"source": "network"},
    ],
)
def test_forged_or_inconsistent_summary(fields):
    t = trip()
    with pytest.raises(ValueError):
        track_bytes(replace(t, summary=replace(t.summary, **fields)), "test", wgs84_confirmed=True)


def test_repeated_time_rejected_even_in_distinct_segments():
    t = trip()
    broken = ((point(), point(1)), (point(1),))
    with pytest.raises(ValueError):
        track_bytes(replace(t, segments=broken), "test", wgs84_confirmed=True)


@pytest.mark.parametrize("lon", [180, 179.99999999999997, -180])
def test_longitude_format_does_not_round_to_invalid_positive_180(lon):
    r = recorder()
    r.append(point(lon=lon), 0)
    r.finish()
    root = ET.fromstring(track_bytes(r.snapshot(), "dateline", wgs84_confirmed=True))
    value = float(root.find("g:trk/g:trkseg/g:trkpt", NS).attrib["lon"])
    assert -180 <= value < 180


def test_success_new_file_private_permissions_and_no_other_changes(tmp_path):
    sentinel = tmp_path / "household.db"
    sentinel.write_bytes(b"never touch this database")
    target = tmp_path / "private.gpx"
    export_track(target, trip(), "test", wgs84_confirmed=True)
    assert sentinel.read_bytes() == b"never touch this database"
    assert len(list(tmp_path.iterdir())) == 2
    assert len(ET.fromstring(target.read_bytes()).findall("g:trk/g:trkseg/g:trkpt", NS)) == 3
    if os.name == "posix":
        assert target.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "dangling"])
def test_never_replaces_existing_target(tmp_path, kind):
    target = tmp_path / "existing.gpx"
    if kind == "file":
        target.write_bytes(b"keep")
    elif kind == "directory":
        target.mkdir()
    else:
        target.symlink_to(tmp_path / ("original" if kind == "symlink" else "missing"))
        if kind == "symlink":
            (tmp_path / "original").write_bytes(b"keep")
    before = sorted(p.name for p in tmp_path.iterdir())
    with pytest.raises(OSError):
        export_track(target, trip(), "test", wgs84_confirmed=True)
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    if kind == "file":
        assert target.read_bytes() == b"keep"
    if kind in ("symlink", "dangling"):
        assert target.is_symlink()


@pytest.mark.parametrize("failure", ["link", "fsync"])
def test_publication_failure_leaves_no_partial_target(tmp_path, monkeypatch, failure):
    def fail(*args):
        raise OSError("simulated filesystem failure")

    monkeypatch.setattr("fieldforge_gps.track_export.os." + failure, fail)
    with pytest.raises(OSError):
        export_track(tmp_path / "out.gpx", trip(), "test", wgs84_confirmed=True)
    assert not list(tmp_path.iterdir())


def test_paused_export_and_capacity_disclosure():
    r = recorder(limit=1)
    r.append(point(), 0)
    raw = track_bytes(r.snapshot(), "partial", wgs84_confirmed=True)
    assert b"POINT LIMIT REACHED" in raw
    r = recorder()
    r.append(point(), 0)
    r.pause()
    assert b"Capture state: paused" in track_bytes(r.snapshot(), "paused", wgs84_confirmed=True)


def test_older_fieldforge_importer_explicitly_refuses_tracks():
    gpx = pytest.importorskip("fieldforge.navigation.gpx")
    with pytest.raises(ValueError, match="routes/tracks"):
        gpx.parse_gpx(track_bytes(trip(), "test", wgs84_confirmed=True))
