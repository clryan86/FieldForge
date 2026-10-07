"""Included atlas controls and external-file consent remain independent."""

import threading
from pathlib import Path

import pytest

from fieldforge_gps import bundled_atlas, map_jobs
from fieldforge_gps.mercator import MercatorView

from .test_mbtiles import pack_file
from .test_places_ui import select, settle
from .test_places_ui import ui as ui


def included_places(ui):
    root, frame, workers = ui
    panel = frame.open_finder()
    workers.append(panel.worker)
    root.update()
    assert panel.included_button.cget("text") == "Included U.S. towns"
    assert str(panel.included_button["state"]) == "normal"
    panel.included_button.invoke()
    settle(root, frame)
    assert panel.catalog is not None and len(panel.catalog.places) == 777
    assert not panel.permission.get() and not panel.wgs84.get()
    return root, frame, panel


def test_included_atlas_button_uses_explicit_region_chooser(ui, monkeypatch):
    root, frame, _ = ui
    assert frame.map_pack is None and not frame.map_trust.get()
    assert frame.included_map_button.cget("text") == "Included U.S. atlas…"
    assert str(frame.included_map_button["state"]) == "normal"
    chosen = []

    def choose(_parent, callback):
        chosen.append("Hawaii")
        callback("Hawaii")

    monkeypatch.setattr("fieldforge_gps.atlas_ui.choose_atlas", choose)
    frame.included_map_button.invoke()
    settle(root, frame)
    assert chosen == ["Hawaii"]
    assert frame.view == MercatorView(*bundled_atlas.REGIONS["Hawaii"])
    assert frame.canvas.find_withtag("map-tile")
    assert not frame.map_trust.get()
    assert str(frame.open_map_button["state"]) == "disabled"


@pytest.mark.parametrize("region", tuple(bundled_atlas.REGIONS))
def test_each_included_region_renders_at_its_own_center_without_external_trust(ui, region):
    root, frame, _ = ui
    assert frame.open_atlas(region)
    settle(root, frame)
    assert frame.map_pack is not None and frame._map_is_bundled
    assert frame.view == MercatorView(*bundled_atlas.REGIONS[region])
    assert frame.canvas.find_withtag("map-tile")
    assert not frame.canvas.find_withtag("bad-tile")
    assert not frame.map_trust.get()
    assert str(frame.open_map_button["state"]) == "disabled"


def test_selected_atlas_region_is_not_replaced_by_loaded_gpx_fit(ui):
    root, frame, _ = ui
    frame.datum.set(True)
    frame.consent.set(True)
    frame.example_button.invoke()
    settle(root, frame)
    document = frame.document
    assert document is not None and frame._points
    assert frame.open_atlas("American Samoa")
    settle(root, frame)
    assert frame.document is document
    assert frame.view == MercatorView(*bundled_atlas.REGIONS["American Samoa"])
    assert frame.canvas.find_withtag("map-tile") and not frame.map_trust.get()


def test_cancelling_region_chooser_preserves_open_atlas(ui, monkeypatch):
    root, frame, _ = ui
    assert frame.open_atlas("Alaska")
    settle(root, frame)
    pack, view, token = frame.map_pack, frame.view, frame._map_reader.token
    monkeypatch.setattr("fieldforge_gps.atlas_ui.choose_atlas", lambda *_a, **_k: None)
    frame.included_map_button.invoke()
    settle(root, frame)
    assert frame.map_pack is pack and frame.view == view
    assert frame._map_reader.token == token and frame._map_is_bundled


def test_included_trenton_requires_selection_without_external_permission(ui):
    root, frame, panel = included_places(ui)
    assert frame.open_atlas("Lower 48 states")
    settle(root, frame)
    assert panel._included_catalog
    assert str(panel.open_button["state"]) == "disabled"
    assert str(panel.search_button["state"]) == "normal"
    panel.query.set("Trenton New Jersey")
    panel.search_button.invoke()
    settle(root, frame)
    assert len(panel._results) == 1
    assert panel._results[0].name == "Trenton"
    assert panel._results[0].region == "New Jersey"
    assert not panel.table.selection()
    assert str(panel.show_button["state"]) == "disabled"
    assert panel.show_selected() is False and frame._place_marker is None
    select(panel)
    panel.show_button.invoke()
    settle(root, frame)
    place, origin = frame._place_marker
    assert (place.name, place.region, origin) == ("Trenton", "New Jersey", "FILE PLACE")
    assert (frame.view.latitude, frame.view.longitude) == pytest.approx(
        (40.2169625, -74.7433553), abs=1e-7
    )
    assert frame.canvas.find_withtag("place-marker")
    assert frame.canvas.find_withtag("map-tile")
    assert not panel.permission.get() and not panel.wgs84.get()
    assert not frame.map_trust.get()


def test_refused_external_map_read_preserves_included_atlas(ui, monkeypatch, tmp_path):
    root, frame, _ = ui
    assert frame.open_atlas("Puerto Rico / U.S. Virgin Islands")
    settle(root, frame)
    pack, view, token = frame.map_pack, frame.view, frame._map_reader.token

    def unexpected_submit(*_args, **_kwargs):
        pytest.fail("A refused external map must not submit a file read")

    monkeypatch.setattr(frame._map_reader, "submit", unexpected_submit)
    assert frame.start_map(tmp_path / "absent.mbtiles") is False
    assert "Nothing was read" in frame.map_status.get()
    assert frame.map_pack is pack and frame.view == view
    assert frame._map_reader.token == token and frame._map_is_bundled
    assert frame.canvas.find_withtag("map-tile") and not frame.map_trust.get()


def test_refused_external_catalog_read_preserves_included_catalog_and_marker(
    ui, monkeypatch, tmp_path
):
    root, frame, panel = included_places(ui)
    panel.query.set("Trenton New Jersey")
    panel.search_button.invoke()
    settle(root, frame)
    select(panel)
    assert panel.show_selected()
    settle(root, frame)
    catalog, marker, results = panel.catalog, frame._place_marker, panel._results
    token = panel.worker.token

    def unexpected_submit(*_args, **_kwargs):
        pytest.fail("A refused external catalogue must not submit a file read")

    monkeypatch.setattr(panel.worker, "submit", unexpected_submit)
    assert panel.start_read(tmp_path / "absent.csv") is False
    assert "Nothing was read" in panel.status.get()
    assert panel.catalog is catalog and panel._results is results
    assert frame._place_marker is marker and panel.worker.token == token
    assert panel._included_catalog and panel.table.selection()
    assert not panel.permission.get() and not panel.wgs84.get()


def test_external_consent_traces_do_not_discard_included_resources(ui):
    root, frame, panel = included_places(ui)
    assert frame.open_atlas("Guam / Northern Mariana Islands")
    settle(root, frame)
    catalog, pack = panel.catalog, frame.map_pack
    frame.map_trust.set(True)
    frame.map_trust.set(False)
    panel.permission.set(True)
    panel.wgs84.set(True)
    panel.permission.set(False)
    panel.wgs84.set(False)
    settle(root, frame)
    assert frame.map_pack is pack and frame._map_is_bundled
    assert panel.catalog is catalog and panel._included_catalog
    assert frame.canvas.find_withtag("map-tile")
    assert str(panel.search_button["state"]) == "normal"
    assert str(frame.open_map_button["state"]) == "disabled"
    assert str(panel.open_button["state"]) == "disabled"


def test_close_and_clear_remove_bundled_permission_state(ui, tmp_path):
    root, frame, panel = included_places(ui)
    assert frame.open_atlas("Hawaii")
    settle(root, frame)
    frame.close_map_button.invoke()
    panel.clear_button.invoke()
    settle(root, frame)
    assert frame.map_pack is None and not frame._map_is_bundled
    assert panel.catalog is None and not panel._included_catalog
    assert not frame.canvas.find_withtag("map-tile")
    assert str(panel.search_button["state"]) == "disabled"
    assert panel.search() is False
    assert frame.start_map(tmp_path / "absent.mbtiles") is False
    assert panel.start_read(tmp_path / "absent.csv") is False
    assert not frame.map_trust.get()
    assert not panel.permission.get() and not panel.wgs84.get()


def test_stale_pending_atlas_cannot_replace_newer_external_pack(ui, monkeypatch, tmp_path):
    root, frame, _ = ui
    external = pack_file(tmp_path)
    atlas_entered, atlas_release = threading.Event(), threading.Event()
    external_entered, external_release = threading.Event(), threading.Event()
    inspect_pack = map_jobs.inspect_pack

    def delayed(path, **kwargs):
        if Path(path) == bundled_atlas.map_path():
            atlas_entered.set()
            assert atlas_release.wait(4), "Atlas worker was not released"
            # Force a successful late result to exercise token rejection even
            # when an old reader finishes after its cancellation was requested.
            kwargs.pop("cancel", None)
        else:
            external_entered.set()
            assert external_release.wait(4), "External worker was not released"
        return inspect_pack(path, **kwargs)

    monkeypatch.setattr(map_jobs, "inspect_pack", delayed)
    try:
        assert frame.open_atlas("Hawaii")
        assert atlas_entered.wait(2)
        atlas_token = frame._map_reader.token
        frame.map_trust.set(True)
        assert frame.start_map(external)
        assert frame._map_reader.token > atlas_token
        assert not frame._map_is_bundled
        atlas_release.set()
        assert external_entered.wait(2)
        frame.after_cancel(frame._map_after)
        frame._map_after = None
        frame._poll_maps()
        assert frame.map_pack is None and frame._map_loading
        external_release.set()
        settle(root, frame)
        assert frame.map_pack is not None and frame.map_pack.name == "Test map"
        assert frame.view == MercatorView(*frame.map_pack.start)
        assert frame.canvas.find_withtag("map-tile")
        assert not frame._map_is_bundled
        frame.map_trust.set(False)
        settle(root, frame)
        assert frame.map_pack is None and not frame.canvas.find_withtag("map-tile")
    finally:
        atlas_release.set()
        external_release.set()
