import hashlib
import json
import os
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from fieldforge_gps import _file_identity
from fieldforge_gps import places as p

CSV = b"name,latitude,longitude,country,region,aliases,source_id,source\nFictional Springs,35,-100,Testland,North,Demo Water|Spring One,a,Original test\nFictional Springs,36,-99,Testland,South,,b,Original test\nFictional Caf\xc3\xa9,34,-101,Testland,North,Test Coffee,c,Original test\n"


def point(name="Example", coordinates=None, **props):
    return {
        "type": "Feature",
        "properties": {"name": name, **props},
        "geometry": {
            "type": "Point",
            "coordinates": [20, 10] if coordinates is None else coordinates,
        },
    }


def geo(features=None, **attrs):
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [point()] if features is None else features,
            **attrs,
        }
    ).encode()


def test_csv_complete_source_fingerprint_and_immutability():
    doc = p.parse_catalog(CSV, "csv")
    assert len(doc.places) == 3 and doc.source_sha256 == hashlib.sha256(CSV).hexdigest()
    assert doc.source_bytes == len(CSV) and doc.format == "csv"
    assert doc.places[0].aliases == ("Demo Water", "Spring One")
    assert doc.places[2].name == "Fictional Café"
    with pytest.raises(FrozenInstanceError):
        doc.places[0].latitude = 0


def test_duplicate_names_and_ids_are_not_conflated():
    data = geo(
        [
            point("Duplicate", [5, 10], source_id="same"),
            point("Duplicate", [6, 11], source_id="same"),
        ]
    )
    doc = p.parse_catalog(data, "geojson")
    result = p.search_places(doc, "Duplicate")
    assert result.total == 2 and [r.ordinal for r in result.places] == [1, 2]
    assert result.places[0].longitude != result.places[1].longitude


@pytest.mark.parametrize(
    "query,names",
    [
        ("fictional springs", ["Fictional Springs", "Fictional Springs"]),
        ("SPRINGS north", ["Fictional Springs"]),
        ("springs south", ["Fictional Springs"]),
        ("cafe", ["Fictional Café"]),
        ("CAFE\u0301", ["Fictional Café"]),
        ("test coffee", ["Fictional Café"]),
        ("water", ["Fictional Springs"]),
        ("testland", ["Fictional Café", "Fictional Springs", "Fictional Springs"]),
        ("missing", []),
        ("", []),
        ("   ", []),
        ("' OR 1=1--", []),
    ],
)
def test_offline_search_normalization_and_context(query, names):
    result = p.search_places(p.parse_catalog(CSV, "csv"), query)
    assert [v.name for v in result.places] == names


def test_unicode_nonlatin_search_retained():
    doc = p.parse_catalog(geo([point("اختبار", country="تجربة"), point("測試城市")]), "geojson")
    assert p.search_places(doc, "اختبار").total == 1
    assert p.search_places(doc, "測試").total == 1


def test_exact_match_alias_prefix_and_substring_order():
    doc = p.parse_catalog(
        geo(
            [
                point("Prefix Exact"),
                point("Exact match"),
                point("Exact"),
                point("Alias target", aliases=["Exact"]),
                point("Other", country="Exact"),
            ]
        ),
        "geojson",
    )
    assert [x.name for x in p.search_places(doc, "exact").places] == [
        "Exact",
        "Alias target",
        "Exact match",
        "Prefix Exact",
        "Other",
    ]


def test_result_limit_total_and_repeatability():
    doc = p.parse_catalog(geo([point(f"Example {n:03}") for n in range(125)]), "geojson")
    a = p.search_places(doc, "example")
    assert a.total == 125 and len(a.places) == 100
    assert p.search_places(doc, "example") == a
    assert len(p.search_places(doc, "example", limit=5).places) == 5


@pytest.mark.parametrize("limit", [0, -1, 101, True, 1.5, "5"])
def test_search_limit_invalid(limit):
    with pytest.raises(ValueError):
        p.search_places(p.parse_catalog(CSV, "csv"), "x", limit=limit)


@pytest.mark.parametrize("query", [None, 42, "x" * 161, " ".join("x" for _ in range(13))])
def test_bad_query(query):
    with pytest.raises(ValueError):
        p.search_places(p.parse_catalog(CSV, "csv"), query)


@pytest.mark.parametrize(
    "lat,lon", [("90", "180"), ("-90", "-180"), ("+.5", "-.5"), ("0", "0"), (" 12.5 ", " 45.25 ")]
)
def test_manual_coordinates(lat, lon):
    loc = p.manual_place(lat, lon)
    assert loc.latitude == float(lat) and loc.longitude == float(lon)
    assert loc.ordinal == 0 and loc.name == "Manual coordinate"


@pytest.mark.parametrize(
    "value",
    [
        True,
        None,
        [],
        {},
        "NaN",
        "Infinity",
        "1e1",
        "35 N",
        "35,4",
        "--5",
        "",
        "1" * 81,
        float("nan"),
        float("inf"),
    ],
)
def test_invalid_coordinate_values(value):
    with pytest.raises(ValueError):
        p.coordinate(value, "latitude")


@pytest.mark.parametrize("lat,lon", [(90.00001, 0), (-90.001, 0), (0, 180.001), (0, -180.001)])
def test_out_of_range_not_clamped(lat, lon):
    with pytest.raises(ValueError):
        p.parse_catalog(geo([point(coordinates=[lon, lat])]), "geojson")


def test_named_geojson_coordinates_use_geometry_not_conflicting_properties():
    doc = p.parse_catalog(
        geo([point("Fictional", [25.5, 12.25, 5], latitude=55, longitude=60)]), "geojson"
    )
    assert (doc.places[0].latitude, doc.places[0].longitude) == (12.25, 25.5)
    assert doc.ignored_elevations == 1


def test_natural_earth_property_adapter_with_fictional_record():
    feature = {
        "type": "Feature",
        "properties": {
            "NAME": "Fictional Café",
            "NAMEASCII": "Fictional Cafe",
            "NAMEALT": "Cafe Test|Fiction",
            "ADM0NAME": "Testland",
            "ADM1NAME": "Test Region",
            "NE_ID": 123,
        },
        "geometry": {"type": "Point", "coordinates": [20, 10]},
    }
    doc = p.parse_catalog(
        geo(
            [feature],
            name="FICTIONAL adapter fixture",
            crs={"type": "name", "properties": {"name": p.CRS84}},
        ),
        "geojson",
    )
    loc = doc.places[0]
    assert loc.country == "Testland" and loc.region == "Test Region" and loc.source_id == "123"
    assert loc.aliases == ("Cafe Test", "Fiction", "Fictional Cafe")
    assert doc.declared_name == loc.source == "FICTIONAL adapter fixture"


@pytest.mark.parametrize(
    "crs",
    [
        None,
        {},
        "EPSG:4326",
        {"type": "name", "properties": {"name": "EPSG:3857"}},
        {"type": "link", "properties": {"href": "https://example.invalid"}},
    ],
)
def test_unsupported_declared_crs_is_rejected(crs):
    with pytest.raises(ValueError, match="CRS"):
        p.parse_catalog(geo(crs=crs), "geojson")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda x: x.update(type="Point"),
        lambda x: x.update(properties=None),
        lambda x: x.update(geometry=None),
        lambda x: x["geometry"].update(type="LineString"),
        lambda x: x["geometry"].update(coordinates=["20", 10]),
        lambda x: x["geometry"].update(coordinates=[20, True]),
        lambda x: x["geometry"].update(coordinates=[20]),
        lambda x: x["geometry"].update(coordinates=[20, 10, 3, 4]),
        lambda x: x["geometry"].update(coordinates=[20, 10, None]),
        lambda x: x.update(crs=None),
        lambda x: x["geometry"].update(crs=None),
        lambda x: x["properties"].update(name=""),
        lambda x: x["properties"].update(name=["Not text"]),
        lambda x: x["properties"].update(name="x" * 161),
        lambda x: x["properties"].update(aliases=["x"] * 17),
        lambda x: x["properties"].update(aliases="x" * 2049),
        lambda x: x["properties"].update(source_id=1.25),
        lambda x: x["properties"].update(country=[]),
    ],
)
def test_bad_record_rejects_whole_file_not_silent_skip(mutate):
    bad = point()
    mutate(bad)
    with pytest.raises(ValueError, match="record 2"):
        p.parse_catalog(geo([point("Valid"), bad]), "geojson")


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\xff",
        b"\x00",
        b"{}",
        b"[]",
        b'{"type":"FeatureCollection","features":[],"features":[]}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b"[[[",
        b'{"x":',
        b"null",
    ],
)
def test_invalid_geojson(data):
    with pytest.raises(ValueError):
        p.parse_catalog(data, "geojson")


def test_json_depth_limit_respects_quoted_braces():
    assert p.parse_catalog(geo([point("[[[[{{{{")]), "geojson").places[0].name == "[[[[{{{{"
    with pytest.raises(ValueError, match="nesting"):
        p.parse_catalog(("[" * 17 + "0" + "]" * 17).encode(), "geojson")


def test_json_work_limit(monkeypatch):
    monkeypatch.setattr(p, "MAX_STRUCTURE", 3)
    with pytest.raises(ValueError, match="work limit"):
        p.parse_catalog(geo(), "geojson")


def test_cleaned_names_remain_inert_and_original_hash_retained():
    data = geo([point("Test\u202e\nName", source="<script>not executed</script>")])
    doc = p.parse_catalog(data, "geojson")
    assert doc.places[0].name == "Test Name"
    assert doc.places[0].source == "<script>not executed</script>"
    assert doc.source_sha256 == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize(
    "data",
    [
        b"wrong,latitude,longitude\nX,1,2",
        b"name,latitude,longitude,name\nX,1,2,Y",
        b"name,latitude,longitude,unknown\nX,1,2,Y",
        b"name,latitude,longitude\nX,1",
        b"name,latitude,longitude\nX,1,2,3",
        b"name,latitude,longitude\n,1,2",
        b"name,latitude,longitude\nX,1e1,2",
        b'name,latitude,longitude\n"not closed,1,2',
        b"name,latitude,longitude\n",
    ],
)
def test_bad_csv(data):
    with pytest.raises(ValueError):
        p.parse_catalog(data, "csv")


def test_csv_bom_quoted_comma_blank_lines_case_headers():
    data = '\ufeffNAME,Latitude,LONGITUDE\r\n"Fictional, Name",+1.25,-2.5\r\n\r\n'.encode()
    doc = p.parse_catalog(data, "csv")
    assert len(doc.places) == 1 and doc.places[0].name == "Fictional, Name"


@pytest.mark.parametrize("format", ["csv", "geojson"])
def test_row_limit_rejects_not_truncates(monkeypatch, format):
    monkeypatch.setattr(p, "MAX_PLACES", 1)
    with pytest.raises(ValueError):
        p.parse_catalog(CSV if format == "csv" else geo([point(), point()]), format)


def test_bytes_limit(monkeypatch):
    monkeypatch.setattr(p, "MAX_BYTES", 10)
    with pytest.raises(ValueError):
        p.parse_catalog(CSV, "csv")


def test_unsupported_format():
    with pytest.raises(ValueError):
        p.parse_catalog(CSV, "xml")


@pytest.mark.parametrize(
    "consent,datum", [(False, False), (True, False), (False, True), (1, True), (True, 1)]
)
def test_permissions_before_filesystem(tmp_path, consent, datum):
    with pytest.raises(ValueError, match="Confirm"):
        p.read_catalog(tmp_path / "not-present.csv", consent=consent, wgs84_confirmed=datum)


@pytest.mark.parametrize(
    "path",
    [
        "https://example.invalid/a.csv",
        "file:/tmp/x.csv",
        "//server/share/a.csv",
        "\\\\server\\share\\a.csv",
    ],
)
def test_network_or_uri_path_rejected(path):
    with pytest.raises(ValueError, match="local place file"):
        p.read_catalog(path, consent=True, wgs84_confirmed=True)


@pytest.mark.parametrize("extension", [".csv", ".CSV", ".geojson", ".json"])
def test_read_only_local_snapshot_paths(tmp_path, extension):
    file = tmp_path / f"space # café{extension}"
    data = CSV if extension.lower() == ".csv" else geo()
    file.write_bytes(data)
    before = set(tmp_path.iterdir())
    file.chmod(0o444)
    try:
        doc = p.read_catalog(file, consent=True, wgs84_confirmed=True)
        assert doc.source_sha256 == hashlib.sha256(data).hexdigest()
        assert file.read_bytes() == data and set(tmp_path.iterdir()) == before
    finally:
        file.chmod(0o644)


def simulate_catalog_clocks(monkeypatch, path, *, changed_stage=None):
    """Keep real file identity but model distinct Windows path/descriptor clocks."""
    original_stat, original_fstat, original_parse = Path.stat, os.fstat, p.parse_catalog
    clock = path.stat().st_ctime_ns
    state = {"descriptor_reads": 0, "parsed": False}

    def clocked(info, *, descriptor=False):
        fields = {
            name: getattr(info, name)
            for name in ("st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        }
        fields["st_ctime_ns"] = clock + (100 if descriptor else 0)
        changed = (
            descriptor and changed_stage == "descriptor" and state["descriptor_reads"] > 1
        ) or (
            not descriptor
            and (
                (changed_stage == "path" and state["descriptor_reads"] > 0)
                or (changed_stage == "parsing" and state["parsed"])
            )
        )
        fields["st_ctime_ns"] += int(changed)
        return SimpleNamespace(**fields)

    def path_stat(selected, *args, **kwargs):
        info = original_stat(selected, *args, **kwargs)
        return clocked(info) if selected == path else info

    def descriptor_stat(fd):
        state["descriptor_reads"] += 1
        return clocked(original_fstat(fd), descriptor=True)

    def parse(*args, **kwargs):
        result = original_parse(*args, **kwargs)
        state["parsed"] = True
        return result

    monkeypatch.setattr(Path, "stat", path_stat)
    monkeypatch.setattr(os, "fstat", descriptor_stat)
    monkeypatch.setattr(p, "parse_catalog", parse)


@pytest.mark.parametrize("windows", [True, False], ids=["windows", "posix"])
def test_catalog_path_and_descriptor_ctime_semantics(tmp_path, monkeypatch, windows):
    path = tmp_path / "places.csv"
    path.write_bytes(CSV)
    simulate_catalog_clocks(monkeypatch, path)
    monkeypatch.setattr(_file_identity, "_WINDOWS", windows)
    if windows:
        doc = p.read_catalog(path, consent=True, wgs84_confirmed=True)
        assert len(doc.places) == 3 and doc.source_sha256 == hashlib.sha256(CSV).hexdigest()
    else:
        with pytest.raises(ValueError, match="changed before"):
            p.read_catalog(path, consent=True, wgs84_confirmed=True)


@pytest.mark.parametrize("changed_stage", ["descriptor", "path", "parsing"])
def test_windows_catalog_rejects_same_api_ctime_changes(tmp_path, monkeypatch, changed_stage):
    path = tmp_path / "places.csv"
    path.write_bytes(CSV)
    simulate_catalog_clocks(monkeypatch, path, changed_stage=changed_stage)
    monkeypatch.setattr(_file_identity, "_WINDOWS", True)
    expected = "changed during parsing" if changed_stage == "parsing" else "changed during reading"
    with pytest.raises(ValueError, match=expected):
        p.read_catalog(path, consent=True, wgs84_confirmed=True)


def test_directory_empty_and_wrong_extension(tmp_path):
    for path in [tmp_path, tmp_path / "empty.csv", tmp_path / "wrong.txt"]:
        if path != tmp_path:
            path.write_bytes(b"" if "empty" in path.name else CSV)
        with pytest.raises(ValueError):
            p.read_catalog(path, consent=True, wgs84_confirmed=True)


def test_changed_source_during_read_rejected(tmp_path, monkeypatch):
    path = tmp_path / "places.csv"
    path.write_bytes(CSV)
    original = p.os.read
    changed = False

    def read(fd, count):
        nonlocal changed
        block = original(fd, count)
        if not changed:
            changed = True
            path.write_bytes(CSV.replace(b"Testland", b"Elsewhere"))
        return block

    monkeypatch.setattr(p.os, "read", read)
    with pytest.raises(ValueError, match="changed"):
        p.read_catalog(path, consent=True, wgs84_confirmed=True)


def test_replaced_source_during_parse_rejected(tmp_path, monkeypatch):
    path = tmp_path / "places.csv"
    path.write_bytes(CSV)
    original = p.parse_catalog

    def parse(*args, **kwargs):
        result = original(*args, **kwargs)
        other = tmp_path / "other.csv"
        other.write_bytes(CSV)
        other.replace(path)
        return result

    monkeypatch.setattr(p, "parse_catalog", parse)
    with pytest.raises(ValueError, match="changed"):
        p.read_catalog(path, consent=True, wgs84_confirmed=True)


def test_cancel_before_read_parse_or_search(tmp_path):
    event = Event()
    event.set()
    with pytest.raises(p.PlaceReadCancelled):
        p.parse_catalog(CSV, "csv", cancel=event)
    with pytest.raises(p.PlaceReadCancelled):
        p.read_catalog(tmp_path / "missing.csv", consent=True, wgs84_confirmed=True, cancel=event)
    with pytest.raises(p.PlaceReadCancelled):
        p.search_places(p.parse_catalog(CSV, "csv"), "x", cancel=event)


def test_cancel_during_parse():
    class Cancellation:
        calls = 0

        def is_set(self):
            self.calls += 1
            return self.calls > 2

    with pytest.raises(p.PlaceReadCancelled):
        p.parse_catalog(CSV, "csv", cancel=Cancellation())


def test_demo_is_clearly_fictional_and_duplicates_preserved():
    data = (Path(p.__file__).parent / "data/FICTIONAL-PLACES.csv").read_bytes()
    doc = p.parse_catalog(data, "csv")
    assert len(doc.places) == 6 and all("FICTIONAL" in loc.source for loc in doc.places)
    assert p.search_places(doc, "fictional springs").total == 2


def test_paired_fictional_csv_and_geojson_geometry_agree():
    root = Path(p.__file__).parent / "data"
    csv = p.parse_catalog((root / "FICTIONAL-PLACES.csv").read_bytes(), "csv")
    geojson = p.parse_catalog((root / "FICTIONAL-PLACES.geojson").read_bytes(), "geojson")
    assert [(v.name, v.latitude, v.longitude, v.country, v.region) for v in csv.places] == [
        (v.name, v.latitude, v.longitude, v.country, v.region) for v in geojson.places
    ]
    assert "FICTIONAL" in geojson.declared_name
