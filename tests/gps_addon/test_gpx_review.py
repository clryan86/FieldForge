import hashlib
import os
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from fieldforge_gps import gpx_review as g
from fieldforge_gps.session import Session
from fieldforge_gps.track_export import export_track


def xml(
    body='<trk><name>Saved track</name><trkseg><trkpt lat="10" lon="20"/></trkseg></trk>', **attrs
):
    values = dict(xmlns=g.NS, version="1.1", creator="test")
    values.update(attrs)
    return (
        "<gpx " + " ".join(f'{k}="{v}"' for k, v in values.items()) + ">" + body + "</gpx>"
    ).encode()


def point_fields(fields="", lat="10", lon="20"):
    return xml(f'<trk><trkseg><trkpt lat="{lat}" lon="{lon}">{fields}</trkpt></trkseg></trk>')


def test_minimal_namespaced_track_keeps_absent_time_and_elevation():
    raw = xml()
    result = g.parse_gpx(raw)
    assert result.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.source_bytes == len(raw)
    assert result.point_count == result.segment_count == 1
    assert result.tracks[0].name == "Saved track"
    assert result.tracks[0].segments[0][0] == g.ReviewPoint(10, 20)
    with pytest.raises(FrozenInstanceError):
        result.tracks[0].name = "overwrite"


def test_multiple_tracks_and_gaps_remain_separate():
    body = '<trk><name>A</name><trkseg><trkpt lat="1" lon="2"/></trkseg><trkseg><trkpt lat="3" lon="4"/></trkseg></trk>'
    body += '<trk><name>B</name><trkseg><trkpt lat="5" lon="6"/></trkseg></trk>'
    result = g.parse_gpx(xml(body))
    assert [t.name for t in result.tracks] == ["A", "B"]
    assert [len(t.segments) for t in result.tracks] == [2, 1]
    assert result.point_count == 3


@pytest.mark.parametrize(
    "raw", [b"", b"garbage", b"<gpx/>", b"\x00", b"\xff", "<gpx/>".encode("utf-16")]
)
def test_reject_bad_input(raw):
    with pytest.raises(ValueError):
        g.parse_gpx(raw)


@pytest.mark.parametrize(
    "attrs",
    [
        dict(xmlns=""),
        dict(xmlns="http://www.topografix.com/GPX/1/0"),
        dict(version="1.0"),
        dict(version="2.0"),
    ],
)
def test_reject_unsupported_gpx_versions_or_namespaces(attrs):
    with pytest.raises(ValueError, match="GPX 1.1"):
        g.parse_gpx(xml(**attrs))


def test_reject_missing_creator():
    with pytest.raises(ValueError):
        g.parse_gpx(xml().replace(b' creator="test"', b""))


@pytest.mark.parametrize(
    "lat,lon",
    [
        ("90.1", "0"),
        ("-90.1", "0"),
        ("0", "180"),
        ("0", "-180.1"),
        ("nan", "0"),
        ("0", "Infinity"),
        ("1e2", "0"),
        ("True", "0"),
        ("", "0"),
        ("1_0", "0"),
        ("0", "9" * 81),
    ],
)
def test_bad_coordinates_reject_whole_document(lat, lon):
    with pytest.raises(ValueError):
        g.parse_gpx(point_fields(lat=lat, lon=lon))


@pytest.mark.parametrize(
    "lat,lon", [("-90", "-180"), ("90", "179.999999999"), ("0", "0"), ("+12.5", "-.5")]
)
def test_coordinate_boundaries_and_decimal_forms(lat, lon):
    result = g.parse_gpx(point_fields(lat=lat, lon=lon))
    point = result.tracks[0].segments[0][0]
    assert point.latitude == float(lat) and point.longitude == float(lon)


@pytest.mark.parametrize(
    "value",
    [
        "2024-01-01T12:30:02Z",
        "2024-01-01T12:30:02.123456789+02:30",
        "2024-01-01T12:30:02.1Z",
        "2024-01-01T12:30:02.1234-02:30",
        "2024-02-29T12:00:00",
        "2024-01-01T12:30:02-14:00",
    ],
)
def test_times_kept_as_supplied_without_invented_timezone(value):
    result = g.parse_gpx(point_fields(f"<time>{value}</time>"))
    assert result.tracks[0].segments[0][0].time_text == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "yesterday",
        "2023-02-29T12:00:00Z",
        "2024-01-01T24:00:00Z",
        "2024-01-01T12:00:60Z",
        "2024-01-01T12:00:00+14:01",
        "2024-01-01T12:00:00+15:00",
        "2024-01-01T12:00:00+00:60",
        "20240101T120000",
        "2024-01-01",
    ],
)
def test_invalid_or_unsupported_times_rejected(value):
    with pytest.raises(ValueError):
        g.parse_gpx(point_fields(f"<time>{value}</time>"))


def test_elevation_and_xml_escaping_are_data_not_markup():
    result = g.parse_gpx(
        xml(
            '<trk><name>A &amp; B &lt;script&gt;</name><trkseg><trkpt lat="1" lon="2"><ele>-3.5</ele></trkpt></trkseg></trk>'
        )
    )
    assert result.tracks[0].name == "A & B <script>"
    assert result.tracks[0].segments[0][0].elevation_m == -3.5


@pytest.mark.parametrize(
    "fields",
    [
        "<ele>NaN</ele>",
        "<ele>1e3000</ele>",
        "<ele/>",
        "<time>2024-01-01T00:00:00Z</time><time>2024-01-01T00:00:01Z</time>",
        "<ele>1</ele><ele>2</ele>",
        "<time><nested/></time>",
    ],
)
def test_bad_optional_point_fields_rejected(fields):
    with pytest.raises(ValueError):
        g.parse_gpx(point_fields(fields))


def test_empty_segments_tracks_routes_and_waypoints_counted_but_not_converted():
    body = '<wpt lat="1" lon="1"/><rte><rtept lat="2" lon="2"/></rte><trk/>'
    body += '<trk><trkseg/><trkseg><trkpt lat="1" lon="1"/></trkseg></trk>'
    result = g.parse_gpx(xml(body))
    assert (
        result.ignored_waypoints,
        result.ignored_routes,
        result.empty_tracks,
        result.empty_segments,
    ) == (1, 1, 1, 1)
    assert result.point_count == 1 and len(result.tracks) == 1


@pytest.mark.parametrize(
    "body",
    ['<wpt lat="1" lon="2"/>', '<rte><rtept lat="1" lon="2"/></rte>', "<trk><trkseg/></trk>"],
)
def test_no_track_points_is_an_error_not_a_route_conversion(body):
    with pytest.raises(ValueError):
        g.parse_gpx(xml(body))


@pytest.mark.parametrize(
    "body",
    [
        '<trkpt lat="1" lon="2"/>',
        '<trk><trkpt lat="1" lon="2"/></trk>',
        "<trk><trkseg><trkseg/></trkseg></trk>",
        '<trk><extensions><trkpt lat="1" lon="2"/></extensions></trk>',
    ],
)
def test_misplaced_core_track_structure_rejected(body):
    with pytest.raises(ValueError, match="Misplaced"):
        g.parse_gpx(xml(body))


@pytest.mark.parametrize(
    "prefix",
    [
        b"<!DOCTYPE gpx>",
        b'<!DOCTYPE gpx [<!ENTITY boom "boom">]>',
        b'<!DOCTYPE gpx SYSTEM "file:///etc/passwd">',
        b'<?xml-stylesheet href="https://example.invalid/x"?>',
    ],
)
def test_dtd_entities_and_processing_instructions_rejected(prefix):
    with pytest.raises(ValueError):
        g.parse_gpx(prefix + xml())


def test_prefixed_namespace_supported():
    raw = xml().replace(b"xmlns=", b"xmlns:g=")
    import re

    raw = re.sub(rb"<(/?)(gpx|trk|name|trkseg|trkpt)([ />])", rb"<\1g:\2\3", raw)
    assert g.parse_gpx(raw).point_count == 1


def test_utf8_bom_and_declaration_supported():
    assert (
        g.parse_gpx(b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?>' + xml()).point_count == 1
    )


def test_non_utf8_encoding_declaration_rejected():
    with pytest.raises(ValueError, match="UTF-8"):
        g.parse_gpx(b'<?xml version="1.0" encoding="ISO-8859-1"?>' + xml())


def test_external_links_and_extensions_not_loaded_or_treated_as_points():
    raw = xml(
        '<metadata><link href="https://example.invalid/private"/></metadata><trk><extensions><e:trkpt xmlns:e="urn:other" lat="99" lon="99"/></extensions><trkseg><trkpt lat="1" lon="2"/></trkseg></trk>'
    )
    assert g.parse_gpx(raw).point_count == 1


def test_name_display_sanitizes_controls_and_preserves_unicode():
    raw = xml('<trk><name>North\u202e\n海</name><trkseg><trkpt lat="1" lon="2"/></trkseg></trk>')
    assert g.parse_gpx(raw).tracks[0].name == "North 海"


@pytest.mark.parametrize(
    "body",
    ["<name>" + "x" * 161 + "</name>", "<name>A</name><name>B</name>", "<name><nested/></name>"],
)
def test_oversize_or_ambiguous_name_rejected(body):
    with pytest.raises(ValueError):
        g.parse_gpx(xml("<trk>" + body + '<trkseg><trkpt lat="1" lon="2"/></trkseg></trk>'))


@pytest.mark.parametrize(
    "constant,value",
    [
        ("MAX_BYTES", 10),
        ("MAX_POINTS", 0),
        ("MAX_TRACKS", 0),
        ("MAX_SEGMENTS", 0),
        ("MAX_ELEMENTS", 2),
        ("MAX_DEPTH", 2),
        ("MAX_TEXT", 3),
    ],
)
def test_all_import_limits_fail_closed(monkeypatch, constant, value):
    monkeypatch.setattr(g, constant, value)
    with pytest.raises(ValueError):
        g.parse_gpx(xml())


def test_deep_nesting_fails_before_recursion_overflow():
    with pytest.raises(ValueError, match="nesting"):
        g.parse_gpx(xml("<extensions>" + "<a>" * 40 + "</a>" * 40 + "</extensions>"))


def test_cancel_before_parse():
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(g.ImportCancelled):
        g.parse_gpx(xml(), cancel=cancel)


def test_cancel_during_parse_no_partial_result(monkeypatch):
    cancel = threading.Event()
    original = g._BoundedBuilder.start

    def start(self, *args):
        if self.count == 3:
            cancel.set()
        return original(self, *args)

    monkeypatch.setattr(g._BoundedBuilder, "start", start)
    with pytest.raises(g.ImportCancelled):
        g.parse_gpx(xml(), cancel=cancel)


def test_old_expat_refused(monkeypatch):
    monkeypatch.setattr(g.expat, "version_info", (2, 5, 0))
    with pytest.raises(ValueError, match="Update Python"):
        g.parse_gpx(xml())


@pytest.mark.parametrize(
    "consent,datum", [(False, False), (True, False), (False, True), (1, True), (True, 1)]
)
def test_permissions_required_before_filesystem_access(consent, datum, tmp_path):
    with pytest.raises(ValueError, match="Confirm"):
        g.read_gpx(tmp_path / "does-not-exist", consent=consent, wgs84_confirmed=datum)


def test_regular_file_is_read_only_and_digest_matches(tmp_path):
    path = tmp_path / "track.gpx"
    path.write_bytes(xml())
    sentinel = tmp_path / "household.db"
    sentinel.write_bytes(b"NOT A REAL DATABASE")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = g.read_gpx(path, consent=True, wgs84_confirmed=True)
    assert result.point_count == 1
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_leaf_symlink_refused(tmp_path):
    path = tmp_path / "track.gpx"
    path.write_bytes(xml())
    link = tmp_path / "link.gpx"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="regular"):
        g.read_gpx(link, consent=True, wgs84_confirmed=True)


def test_directory_refused(tmp_path):
    with pytest.raises(ValueError, match="regular"):
        g.read_gpx(tmp_path, consent=True, wgs84_confirmed=True)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX pipe test")
def test_fifo_refused_without_blocking(tmp_path):
    path = tmp_path / "pipe.gpx"
    os.mkfifo(path)
    with pytest.raises(ValueError, match="regular"):
        g.read_gpx(path, consent=True, wgs84_confirmed=True)


def test_changed_file_rejected_after_read(tmp_path, monkeypatch):
    path = tmp_path / "track.gpx"
    path.write_bytes(xml())
    old = g._signature
    count = 0

    def signature(info):
        nonlocal count
        count += 1
        result = old(info)
        return (*result[:-1], result[-1] + 1) if count == 4 else result

    monkeypatch.setattr(g, "_signature", signature)
    with pytest.raises(ValueError, match="changed during"):
        g.read_gpx(path, consent=True, wgs84_confirmed=True)


def test_read_cancelled_before_open(tmp_path):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(g.ImportCancelled):
        g.read_gpx(tmp_path / "absent", consent=True, wgs84_confirmed=True, cancel=cancel)


def test_fieldforge_02_export_round_trip_all_points_segments_times(tmp_path):
    source = Path(__file__).parents[2] / "fieldforge_gps/data/SYNTHETIC-TRIP.nmea"
    session = Session("recorded")
    session.start_recording(source, collect_track=True, wgs84_confirmed=True, consent=True)
    assert session.wait(3)
    original = session.trip_snapshot()
    assert original.summary.point_count == 30
    path = tmp_path / "roundtrip.gpx"
    export_track(path, original, "ROUND TRIP", wgs84_confirmed=True)
    review = g.read_gpx(path, consent=True, wgs84_confirmed=True)
    assert review.point_count == 30 and review.segment_count == 3
    for a, b in zip(original.segments, review.tracks[0].segments):
        for old, new in zip(a, b):
            assert abs(old.latitude - new.latitude) < 1e-7
            assert abs(old.longitude - new.longitude) < 1e-7
            assert new.time_text is not None
            from datetime import datetime

            assert datetime.fromisoformat(new.time_text.replace("Z", "+00:00")) == old.timestamp
    assert session.trip_snapshot() == original
    session.stop()


def test_exact_50000_point_capacity_and_one_over_rejection():
    points = '<trkpt lat="1" lon="2"/>' * g.MAX_POINTS
    raw = xml("<trk><trkseg>" + points + "</trkseg></trk>")
    assert g.parse_gpx(raw).point_count == 50_000
    with pytest.raises(ValueError, match="50,000"):
        g.parse_gpx(xml("<trk><trkseg>" + points + '<trkpt lat="1" lon="2"/></trkseg></trk>'))


def test_all_packaged_review_sample_data_is_explicitly_fictional():
    path = Path(__file__).parents[2] / "fieldforge_gps/data/FICTIONAL-REVIEW.gpx"
    result = g.parse_gpx(path.read_bytes())
    assert result.point_count == 34 and result.segment_count == 4
    assert all("FICTIONAL" in t.name for t in result.tracks)
