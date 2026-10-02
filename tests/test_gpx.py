import os
import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest

from fieldforge.app import FieldForgeApp
from fieldforge.navigation.gpx import (
    NS,
    GPXExport,
    capture_export,
    commit_import,
    parse_gpx,
    preview_import,
    read_gpx,
    render_gpx,
    save_gpx,
)
from fieldforge.navigation.places import PlaceConflict, PlaceStore, make_place


@pytest.fixture
def store(tmp_path):
    return PlaceStore(FieldForgeApp(tmp_path / "app.db").db.path)


def gpx(content='<wpt lat="0" lon="1"><name>Practice A</name><type>meeting</type><desc>Private &amp; exact</desc></wpt>'):
    return f'<gpx xmlns="{NS}" version="1.1" creator="Fictional tests">{content}</gpx>'.encode()


def test_parse_required_coordinates_and_escaped_text_no_database_mutation(store):
    before = store.path.read_bytes()
    capture = parse_gpx(gpx())
    assert capture.points[0] == make_place("Practice A", 0, 1, "meeting", "Private & exact")
    plan = preview_import(store, capture)
    assert plan.states == ("new",) and plan.added == 1
    assert store.path.read_bytes() == before


def test_plain_names_optional_and_omitted_fields_explicit():
    capture = parse_gpx(gpx('<metadata><name>Not imported</name></metadata><wpt lat="1" lon="2">'
                            '<ele>999</ele><time>2020-01-01T00:00:00Z</time><cmt>Not a desc</cmt>'
                            '<extensions><arbitrary><private>data</private></arbitrary></extensions></wpt>'))
    assert capture.points[0].name == "Imported waypoint 1"
    assert capture.generated_names == 1 and not capture.points[0].notes
    assert capture.omitted == ("metadata: 1", "waypoint cmt: 1", "waypoint ele: 1", "waypoint extensions: 1", "waypoint time: 1")


@pytest.mark.parametrize("body", ['<rte><rtept lat="0" lon="0"/></rte>', '<trk/>', '<unexpected/>',
    '<wpt lat="1"/>', '<wpt lat="91" lon="0"/>', '<wpt lat="0" lon="180"/>',
    '<wpt lat="0" lon="nan"/>', '<wpt lat="1e1" lon="2"/>',
    '<wpt lat="1" lon="2"><name>A</name><name>B</name></wpt>',
    '<wpt lat="1" lon="2"><name><b>Nested</b></name></wpt>', '<wpt lat="1" lon="2"><bad/></wpt>',
    '<wpt lat="1" lon="2"><name a="b">Bad</name></wpt>', '<metadata/>', '<wpt'])
def test_unsupported_content_is_not_silently_imported(body):
    with pytest.raises(ValueError):
        parse_gpx(gpx(body))


@pytest.mark.parametrize("raw", [b"", b"<gpx/>", b"\xff", b"not xml",
    b'<gpx xmlns="http://www.topografix.com/GPX/1/0" version="1.0" creator="test"/>',
    ('<?xml version="1.0" encoding="ISO-8859-1"?>'+gpx().decode()).encode(),
    ('<?xml version="1.1"?>'+gpx().decode()).encode(),
    b'<!DOCTYPE gpx [<!ENTITY x SYSTEM "file:///etc/passwd">]>'+gpx(),
    b'<?xml-stylesheet href="https://example.invalid/style"?>'+gpx(),
    ('<!DOCTYPE gpx [<!ENTITY a "123"><!ENTITY b "&a;&a;">]>'+gpx().decode()).encode()])
def test_untrusted_xml_encodings_doctypes_and_pi_are_rejected(raw):
    with pytest.raises(ValueError):
        parse_gpx(raw)


def test_no_remote_or_local_entity_resolution(store, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Network attempted")
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, fail)
    data = parse_gpx(gpx('<wpt lat="0" lon="0"><name>&lt;script&gt;data&lt;/script&gt;</name></wpt>'))
    commit_import(store, preview_import(store, data), acknowledged=True)
    assert store.snapshot().records[0].point.name == "<script>data</script>"


def test_file_snapshot_is_stable_after_source_changes(tmp_path, store):
    path = tmp_path / "places.gpx"
    path.write_bytes(gpx())
    plan = preview_import(store, read_gpx(path))
    path.write_bytes(b"changed")
    assert commit_import(store, plan, acknowledged=True) == (1, 0)
    assert store.snapshot().records[0].point.name == "Practice A"


def test_bounded_input_depth_nodes_and_waypoint_count(monkeypatch):
    from fieldforge.navigation import gpx as module
    with pytest.raises(ValueError, match="1 MiB"):
        parse_gpx(b"x"*(module.MAX_INPUT+1))
    with pytest.raises(ValueError, match="bounds"):
        parse_gpx(gpx('<extensions>'+('<x>'*20)+('</x>'*20)+'</extensions>'))
    with pytest.raises(ValueError, match="bounds"):
        parse_gpx(gpx('<extensions>'+'<x/>'*6000+'</extensions>'))
    with pytest.raises(ValueError, match="200"):
        parse_gpx(gpx('<wpt lat="0" lon="0"/>'*201))
    with pytest.raises(ValueError, match="too long"):
        parse_gpx(gpx('<wpt lat="0" lon="0"><desc>'+'a'*4001+'</desc></wpt>'))


def test_consent_no_overwrite_duplicates_and_atomic_conflicts(store):
    captured = parse_gpx(gpx())
    plan = preview_import(store, captured)
    for choice in (False, None, 1, "yes"):
        with pytest.raises(ValueError):
            commit_import(store, plan, acknowledged=choice)
    assert commit_import(store, plan, acknowledged=True) == (1, 0)
    same = preview_import(store, captured)
    before = store.path.read_bytes()
    assert same.duplicates == 1 and commit_import(store, same, acknowledged=True) == (0, 1)
    assert store.path.read_bytes() == before
    conflict = parse_gpx(gpx('<wpt lat="0" lon="2"><name>practice a</name></wpt><wpt lat="0" lon="4"><name>New</name></wpt>'))
    preview = preview_import(store, conflict)
    assert preview.states == ("conflict", "new")
    with pytest.raises(PlaceConflict, match="conflicts"):
        commit_import(store, preview, acknowledged=True)
    assert store.path.read_bytes() == before


def test_duplicate_and_conflicting_names_within_input_are_handled(store):
    child = '<wpt lat="0" lon="1"><name>A</name></wpt>'
    plan = preview_import(store, parse_gpx(gpx(child+child)))
    assert plan.states == ("new", "duplicate")
    assert commit_import(store, plan, acknowledged=True) == (1, 1)
    fresh = preview_import(store, parse_gpx(gpx(child+'<wpt lat="0" lon="2"><name>A</name></wpt>')))
    assert fresh.states == ("duplicate", "conflict")


def test_edits_after_preview_reject_entire_import(store):
    plan = preview_import(store, parse_gpx(gpx()))
    original = store.save(make_place("Other", 0, 4))
    with pytest.raises(PlaceConflict, match="changed since"):
        commit_import(store, plan, acknowledged=True)
    refreshed = preview_import(store, plan.captured)
    store.save(replace(original.point, notes="Changed unrelated waypoint"), expected=original)
    with pytest.raises(PlaceConflict):
        commit_import(store, refreshed, acknowledged=True)
    assert len(store.snapshot().records) == 1


def test_concurrent_imports_and_capacity_checks_are_transactional(store, monkeypatch):
    plan = preview_import(store, parse_gpx(gpx()))
    def commit(_):
        try:
            commit_import(store, plan, acknowledged=True)
            return "saved"
        except PlaceConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(commit, range(2))) == ["conflict", "saved"]
    from fieldforge.navigation import gpx as module
    monkeypatch.setattr(module, "MAX_PLACES", 1)
    second = preview_import(store, parse_gpx(gpx('<wpt lat="0" lon="3"><name>B</name></wpt>')))
    with pytest.raises(ValueError, match="limit"):
        commit_import(store, second, acknowledged=True)
    assert len(store.snapshot().records) == 1


def test_failure_rolls_back_all_imported_points(store):
    plan = preview_import(store, parse_gpx(gpx('<wpt lat="0" lon="1"><name>A</name></wpt><wpt lat="0" lon="2"><name>B</name></wpt>')))
    with store.connect() as db:
        db.execute("CREATE TRIGGER deny_b BEFORE INSERT ON waypoints WHEN NEW.name='B' BEGIN SELECT RAISE(ABORT,'simulated'); END")
    with pytest.raises(sqlite3.IntegrityError):
        commit_import(store, plan, acknowledged=True)
    assert not store.snapshot().records


def test_export_notes_separate_and_original_coordinates_not_changed(store):
    point = store.save(make_place("Café & <B>", 0.00000001, 180, notes="PRIVATE_NOTE\r\n\n"))
    public = capture_export(store, (point.point.id,))
    assert not public.points[0].notes and b"PRIVATE_NOTE" not in render_gpx(public)
    root = ET.fromstring(render_gpx(public))
    child = root.find(f"{{{NS}}}wpt")
    assert child.attrib == {"lat": "0.00000001", "lon": "-180.0"}
    assert child.find(f"{{{NS}}}name").text == "Café & <B>"
    assert store.snapshot().records == (point,)
    private = capture_export(store, (point.point.id,), include_notes=True)
    parsed = parse_gpx(render_gpx(private))
    assert parsed.points[0].notes == "PRIVATE_NOTE\r\n\n"
    with pytest.raises(ValueError, match="opt-in"):
        render_gpx(replace(private, include_notes=False))


def test_export_uses_captured_version_and_only_selected_places(store, tmp_path):
    a = store.save(make_place("A", 0, 1))
    b = store.save(make_place("B", 0, 2))
    captured = capture_export(store, (b.point.id,))
    store.remove(b)
    output = save_gpx(captured, tmp_path / "new.gpx", acknowledged=True)
    assert parse_gpx(output.path.read_bytes()).points[0].name == "B"
    assert len(parse_gpx(output.path.read_bytes()).points) == 1
    assert store.snapshot().records == (a,)
    with pytest.raises(FileExistsError):
        save_gpx(captured, output.path, acknowledged=True)
    with pytest.raises(ValueError):
        save_gpx(captured, tmp_path / "missing.gpx")
    with pytest.raises(ValueError):
        save_gpx(captured, tmp_path / "bad.db", acknowledged=True)


def test_file_errors_and_cleanup_never_delete_existing_destination(store, tmp_path, monkeypatch):
    captured = GPXExport((make_place("A", 0, 1),))
    target = tmp_path / "new.gpx"
    def fail(_):
        raise OSError("flush failure")
    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError):
        save_gpx(captured, target, acknowledged=True)
    assert not target.exists()
    target.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        save_gpx(captured, target, acknowledged=True)
    assert target.read_bytes() == b"keep"
    with pytest.raises(ValueError):
        read_gpx(tmp_path / "file.txt")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO test")
def test_pipe_rejected_without_waiting_for_writer(tmp_path):
    path = tmp_path / "pipe.gpx"
    os.mkfifo(path)
    with pytest.raises(ValueError, match="regular"):
        read_gpx(path)
