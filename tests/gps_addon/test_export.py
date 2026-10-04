import hashlib
from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest

from fieldforge_gps.export import NS, export_waypoint, waypoint_bytes
from fieldforge_gps.session import PositionState, Snapshot

from .test_nmea import rmc
from .test_session import WALL


def shot(mode="recorded", **changes):
    state = PositionState(mode)
    raw = rmc(**changes)
    state.consume(raw, 0)
    return Snapshot(
        mode, "test", state.position, 1, 0, 0, 0, None, hashlib.sha256(raw).hexdigest(), False
    )


def test_gpx_explicit_recorded_provenance_and_escaped_name():
    raw = waypoint_bytes(shot(), "A & <B>", wgs84_confirmed=True)
    root = ET.fromstring(raw)
    point = root.find(f"{{{NS}}}wpt")
    assert point.find(f"{{{NS}}}name").text == "RECORDED — A & <B>"
    assert "NOT live" in point.find(f"{{{NS}}}desc").text
    assert "Receiver UTC: 2026-10-02T12:00:00+00:00" in point.find(f"{{{NS}}}desc").text
    assert root.find(f"{{{NS}}}trk") is None
    assert root.find(f"{{{NS}}}rte") is None
    assert b"accuracy guarantee" in raw
    assert b"private-device" not in raw


def test_serial_not_mislabeled_recorded():
    raw = waypoint_bytes(shot("serial"), "GPS", wgs84_confirmed=True)
    assert b"RECORDED" not in raw and b"Local serial GPS receiver" in raw


def test_date_line_normalized():
    root = ET.fromstring(waypoint_bytes(shot(lon="18000.0"), "East", wgs84_confirmed=True))
    assert float(root.find(f"{{{NS}}}wpt").attrib["lon"]) == -180


@pytest.mark.parametrize("name", ["", "  ", "x" * 121, "a\x00b", "\x1b", "\ud800", "\ufffe"])
def test_names_rejected(name):
    with pytest.raises(ValueError):
        waypoint_bytes(shot(), name, wgs84_confirmed=True)


def test_requires_datum_and_position():
    with pytest.raises(ValueError):
        waypoint_bytes(shot(), "x", wgs84_confirmed=False)
    with pytest.raises(ValueError):
        waypoint_bytes(replace(shot(), position=None), "x", wgs84_confirmed=True)
    with pytest.raises(ValueError):
        waypoint_bytes(replace(shot(), recording_sha256=""), "x", wgs84_confirmed=True)
    p = replace(shot().position, timestamp=WALL.replace(tzinfo=None))
    with pytest.raises(ValueError):
        waypoint_bytes(replace(shot(), position=p), "x", wgs84_confirmed=True)


def test_new_file_and_no_overwrite(tmp_path):
    p = tmp_path / "position.gpx"
    export_waypoint(p, shot(), "One", wgs84_confirmed=True)
    before = p.read_bytes()
    with pytest.raises(FileExistsError):
        export_waypoint(p, shot(), "Two", wgs84_confirmed=True)
    assert p.read_bytes() == before
    assert list(tmp_path.iterdir()) == [p]


def test_existing_symlink_not_replaced(tmp_path):
    target = tmp_path / "important"
    target.write_bytes(b"keep")
    link = tmp_path / "link.gpx"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        export_waypoint(link, shot(), "One", wgs84_confirmed=True)
    assert target.read_bytes() == b"keep" and link.is_symlink()
    assert len(list(tmp_path.iterdir())) == 2


def test_failed_publication_removes_temporary_file(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError("hard links unavailable")

    monkeypatch.setattr("fieldforge_gps.export.os.link", fail)
    with pytest.raises(OSError):
        export_waypoint(tmp_path / "new.gpx", shot(), "One", wgs84_confirmed=True)
    assert not list(tmp_path.iterdir())


def test_fieldforge_waypoint_import_compatibility():
    gpx = pytest.importorskip("fieldforge.navigation.gpx")
    captured = gpx.parse_gpx(waypoint_bytes(shot(), "Source", wgs84_confirmed=True))
    assert len(captured.points) == 1
    p = captured.points[0]
    assert p.latitude == 10 and p.longitude == 20
    assert p.kind == "recorded-gps"
    assert "NOT live" in p.notes and "Receiver UTC:" in p.notes
