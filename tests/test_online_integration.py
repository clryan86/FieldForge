"""Actual portal/client/desktop handoffs, then continued use with no network."""

import gc
import os
import socket
import threading
import time
from xml.etree import ElementTree as ET

import pytest
from map_fixture import make_map
from test_online_server import _FakeProvider, _raw_config

from fieldforge.app import FieldForgeApp
from fieldforge.navigation.map_view import Viewport
from fieldforge.navigation.mbtiles import inspect_pack, read_frame
from fieldforge.navigation.places import PlaceStore, make_place
from fieldforge.online.catalog import publish_map
from fieldforge.online.client import PortalClient, PortalOffline
from fieldforge.online.server import PortalConfig, make_server
from fieldforge.online.storage import PortalLibrary
from fieldforge.ui.portal_integration import place_fields


@pytest.fixture
def operated_portal(tmp_path, request):
    provider = _FakeProvider()
    request.addfinalizer(provider.close)
    provider.geocoding.append({
        "display_name": "Fixture Depot B, Test County", "lat": "40.02", "lon": "-75.01",
    })
    catalog_root = tmp_path / "published-maps"
    source = make_map(tmp_path / "synthetic-overview.mbtiles", zooms=(0,))
    asset = publish_map(
        catalog_root, source, map_id="synthetic-overview-v1", title="Synthetic test overview",
        attribution="Original FieldForge test fixture", license="Test fixture only",
        coverage="Fictional grid for integration verification; no real map coverage", version="1",
    )
    server = make_server(PortalConfig.from_dict(_raw_config(catalog_root, provider)))
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", provider, source, asset
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert not thread.is_alive()


def test_real_downloads_and_coordinates_survive_a_fresh_offline_open(operated_portal, tmp_path, monkeypatch):
    url, provider, source, asset = operated_portal
    app = FieldForgeApp(tmp_path / "personal" / "app.db")
    library = PortalLibrary(app.db.path.parent / "online-maps")
    client = PortalClient(url)
    assert not client.connected and provider.requests == []
    with pytest.raises(PortalOffline):
        client.search("Fixture Depot")
    client.connect()
    assert provider.requests == []  # Reachability checks do not submit an address.
    results = client.search("Fixture Depot")
    assert len(results) == 2
    chosen = results[1]
    saved = PlaceStore(app.db.path).save(make_place(**place_fields(chosen)))
    assert (saved.point.latitude, saved.point.longitude) == (40.02, -75.01)
    assert chosen["attribution"] in saved.point.notes
    downloaded = client.download(client.catalog()[0], library.maps_directory)
    assert downloaded.read_bytes() == source.read_bytes()
    assert downloaded.name == asset["filename"]
    routes = client.routes((40.0, -75.0), (40.02, -75.01))
    assert len(routes) == 2 and routes[0]["geometry"] != routes[1]["geometry"]
    saved_routes = tuple(library.save_route(route) for route in routes)
    client.disconnect()

    def offline(*_args, **_kwargs):
        pytest.fail("Offline reopening must not create a network connection")

    monkeypatch.setattr(socket, "create_connection", offline)
    fresh = PortalLibrary(library.root)
    assert fresh.maps() == (downloaded,)
    assert set(fresh.routes()) == set(saved_routes)
    route = fresh.load_route(saved_routes[1])
    assert route["steps"][1]["instruction"] == "Turn right onto Test Lane."
    assert route["geometry"][0] == [-75.0, 40.0]
    frame = read_frame(inspect_pack(downloaded), Viewport(40.0, -75.0, 0, 512, 512))
    assert any(tile.data for tile in frame.tiles)
    gpx = fresh.export_gpx(route, tmp_path / "saved-plan.gpx")
    tree = ET.fromstring(gpx.read_bytes())
    namespaces = {"g": "http://www.topografix.com/GPX/1/1"}
    assert tree.find("g:trk/g:type", namespaces).text == "planned-route"
    assert tree.findall(".//g:trkpt/g:time", namespaces) == []
    assert len(tree.findall(".//g:trkpt", namespaces)) == len(route["geometry"])
    assert PlaceStore(app.db.path).snapshot().records[0].point == saved.point


def test_place_prefill_preserves_full_address_source_and_coordinate_precision():
    result = {
        "label": "A" * 220, "latitude": 0.000000123456789, "longitude": -75.123456789,
        "source": "Test source", "attribution": "Test attribution", "license": "Test license",
        "retrieved_at": "2026-10-03T20:00:00Z",
    }
    fields = place_fields(result)
    assert len(fields["name"]) == 200 and result["label"] in fields["notes"]
    point = make_place(**fields)
    assert point.latitude == result["latitude"] and point.longitude == result["longitude"]
    assert "Test attribution" in point.notes and result["retrieved_at"] in point.notes


def _wait(root, *panels):
    deadline = time.monotonic() + 10
    idle_since = None
    while time.monotonic() < deadline:
        root.update()
        if all(not panel.busy and not getattr(panel, "_resize_id", None) for panel in panels):
            idle_since = idle_since or time.monotonic()
            if time.monotonic() - idle_since > .12:
                return
        else:
            idle_since = None
        time.sleep(.005)
    pytest.fail("Workflow did not finish: " + "; ".join(p.status.get() for p in panels))


def test_desktop_fills_existing_places_opens_map_and_reuses_route_offline(
    operated_portal, tmp_path, monkeypatch,
):
    import tkinter as tk
    from tkinter import ttk

    from fieldforge.ui.gps import install_gps_menu
    from fieldforge.ui.maps import MapsTab
    from fieldforge.ui.places import PlacesTab
    from fieldforge.ui.portal_integration import install_online_maps

    gc.collect()
    try:
        root = tk.Tk()
    except tk.TclError:
        if os.environ.get("FIELDFORGE_REQUIRE_GUI") == "1":
            pytest.fail("Online map integration requires a functioning Tk display")
        pytest.skip("Graphical portal handoff runs in the dedicated GUI jobs")
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *args, **kwargs: True)
    monkeypatch.setattr("webbrowser.open", lambda *args, **kwargs: False)
    root.geometry("1000x700")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    app = FieldForgeApp(tmp_path / "desktop.db")
    menu = tk.Menu(root)
    root.configure(menu=menu)
    gps = install_gps_menu(root, menu)
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)
    places = PlacesTab(notebook, app.db.path)
    maps = MapsTab(notebook, app.db.path)
    notebook.add(places, text="Places")
    notebook.add(maps, text="Maps")
    panel = install_online_maps(notebook, app.db.path, places, maps, gps, menu)
    try:
        notebook.select(panel)
        _wait(root, panel)
        assert not panel.connected
        assert str(panel.search_entry["state"]) == "disabled"
        panel.portal_url.set(operated_portal[0])
        panel.connect()
        _wait(root, panel)
        panel.query.set("Fixture Depot")
        panel.search()
        _wait(root, panel)
        assert panel.selected_result is None  # Ambiguous results were not auto-selected.
        panel.results_tree.selection_set("0")
        panel.select_result()
        panel.use_start()
        panel.results_tree.selection_set("1")
        panel.select_result()
        panel.use_destination()
        panel.save_place()
        assert places.dialog is not None and not app.waypoints()
        assert places.dialog.fields["latitude"].get() == "40.02"
        places.dialog.save_button.invoke()
        root.update()
        assert places.dialog is None and app.waypoints()[0].longitude == -75.01

        notebook.select(panel)
        panel.refresh_catalog()
        _wait(root, panel)
        panel.maps_tree.selection_set("0")
        panel.select_map()
        panel.download_selected()
        _wait(root, panel, maps)
        assert maps.pack_info is not None and maps.frame is not None
        notebook.select(panel)
        panel.request_route()
        _wait(root, panel)
        panel.route_tree.selection_set("1")
        panel.select_route()
        panel.save_route()
        _wait(root, panel)
        route_path = panel.library.routes()[0]
        panel.disconnect()

        def no_network(*_args, **_kwargs):
            pytest.fail("A saved desktop route must work disconnected")

        monkeypatch.setattr(socket, "create_connection", no_network)
        panel.open_route_path(route_path)
        _wait(root, panel)
        panel.show_route()
        _wait(root, maps)
        assert maps.route["id"] == panel.current_route["id"]
        assert not panel.connected and str(panel.search_entry["state"]) == "disabled"
        assert "Turn right onto Test Lane." in panel.route_steps.get("1.0", "end")
        assert notebook.select() == str(maps)
        assert (panel.start_lat.get(), panel.end_lon.get()) == ("40.0", "-75.01")
        assert panel.can_close()
    finally:
        panel.close()
        gps.close()
        root.destroy()
        panel._worker.shutdown(wait=True, cancel_futures=True)
        maps._worker.shutdown(wait=True, cancel_futures=True)
        gc.collect()
    assert not errors
