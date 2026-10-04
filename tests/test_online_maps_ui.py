"""Real Tk checks for the optional portal and its durable offline handoffs."""

import gc
import hashlib
import json
import os
import shutil
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from map_fixture import make_map

from fieldforge.app import FieldForgeApp


@dataclass
class Delay:
    started: threading.Event
    release: threading.Event
    finished: threading.Event
    cancel: threading.Event | None = None


class FakePortal:
    """Deterministic service double; deliberately ignores late cancellation."""

    def __init__(self, base_url, factory):
        self.base_url = base_url
        self.factory = factory
        self.connected = False
        self.capabilities = {}
        self.calls = []
        self.delays = {}
        self.errors = {}

    def delay(self, operation):
        delayed = Delay(threading.Event(), threading.Event(), threading.Event())
        self.delays[operation] = delayed
        self.factory.delays.append(delayed)
        return delayed

    def _begin(self, operation, values=(), *, cancel=None):
        self.calls.append((operation, values, threading.get_ident()))
        delayed = self.delays.get(operation)
        if delayed is not None:
            delayed.cancel = cancel
            delayed.started.set()
            assert delayed.release.wait(5), f"{operation} worker was never released"
        if operation in self.errors:
            raise self.errors[operation]

    def _finish(self, operation):
        delayed = self.delays.get(operation)
        if delayed is not None:
            delayed.finished.set()

    def connect(self, *, cancel=None):
        self._begin("connect", cancel=cancel)
        self.capabilities = dict(self.factory.status)
        self.connected = True
        self._finish("connect")
        return dict(self.capabilities)

    def disconnect(self):
        self.calls.append(("disconnect", (), threading.get_ident()))
        self.connected = False

    def search(self, query, *, cancel=None):
        self._begin("search", (query,), cancel=cancel)
        self._finish("search")
        return tuple(dict(result) for result in self.factory.addresses)

    def catalog(self, *, cancel=None):
        self._begin("catalog", cancel=cancel)
        self._finish("catalog")
        return (dict(self.factory.asset),)

    def routes(self, start, end, *, cancel=None):
        self._begin("routes", (start, end), cancel=cancel)
        self._finish("routes")
        return tuple(dict(route) for route in self.factory.routes)

    def download(self, asset, directory, *, cancel=None, progress=None, resume=False):
        self.last_resume = resume
        from fieldforge.online.storage import publish_map

        self._begin("download", (dict(asset), Path(directory)), cancel=cancel)
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / asset["filename"]
        temporary = directory / ".test-download.tmp"
        shutil.copyfile(self.factory.map_source, temporary)
        assert hashlib.sha256(temporary.read_bytes()).hexdigest() == asset["sha256"]
        try:
            publish_map(temporary, path, asset, self.base_url, lambda: None)
        finally:
            temporary.unlink(missing_ok=True)
        if progress is not None:
            progress(path.stat().st_size, asset["bytes"])
        self._finish("download")
        return path


class PortalFactory:
    def __init__(self, map_source):
        self.map_source = map_source
        self.clients = []
        self.delays = []
        self.status = {
            "api_version": 1,
            "name": "Fictional test portal",
            "geocoding": True,
            "routing": True,
            "catalog": True,
            "route_modes": ["driving"],
        }
        attribution = "Original fictional software test data, not for navigation."
        self.addresses = (
            {
                "label": "Fictional test destination A",
                "latitude": 0.0,
                "longitude": -0.00000001,
                "source": "Fictional test geocoder",
                "attribution": attribution,
                "license": "CC0-1.0",
                "retrieved_at": "2026-10-04T00:00:00Z",
            },
            {
                "label": "Fictional test destination B",
                "latitude": 1.25,
                "longitude": 2.5,
                "source": "Fictional test geocoder",
                "attribution": attribution,
                "license": "CC0-1.0",
                "retrieved_at": "2026-10-04T00:00:00Z",
            },
        )
        self.asset = {
            "id": "fictional-training-map",
            "title": "Fictional training map",
            "filename": "fictional-training.mbtiles",
            "format": "mbtiles",
            "download_path": "/api/v1/maps/fictional-training-map/download",
            "bytes": map_source.stat().st_size,
            "sha256": hashlib.sha256(map_source.read_bytes()).hexdigest(),
            "attribution": attribution,
            "license": "CC0-1.0",
            "coverage": "Fictional test grid",
            "version": "test-1",
        }
        route = {
            "id": "fictional-route-a",
            "title": "Fictional primary route",
            "mode": "driving",
            "distance_m": 1200.0,
            "duration_s": 180.0,
            "geometry": [[0.0, 0.0], [0.005, 0.005], [0.01, 0.01]],
            "steps": [
                {
                    "instruction": "Continue along Fictional Test Road.",
                    "distance_m": 600.0,
                    "duration_s": 90.0,
                    "latitude": 0.0,
                    "longitude": 0.0,
                },
                {
                    "instruction": "Arrive at the fictional destination.",
                    "distance_m": 600.0,
                    "duration_s": 90.0,
                    "latitude": 0.005,
                    "longitude": 0.005,
                },
            ],
            "start": {"latitude": 0.0, "longitude": 0.0},
            "end": {"latitude": 0.01, "longitude": 0.01},
            "source": "Fictional test router",
            "attribution": attribution,
            "license": "CC0-1.0",
            "created_at": "2026-10-04T00:00:00Z",
        }
        alternative = dict(route, id="fictional-route-b", title="Fictional alternative route")
        self.routes = (route, alternative)

    def __call__(self, base_url):
        client = FakePortal(base_url, self)
        self.clients.append(client)
        return client


@pytest.fixture
def screen(tmp_path, monkeypatch):
    gc.collect()
    required = os.environ.get("FIELDFORGE_REQUIRE_GUI") == "1"
    try:
        import tkinter as tk
    except ImportError as exc:
        if required:
            pytest.fail(f"FIELDFORGE_REQUIRE_GUI=1 requires tkinter: {exc}")
        pytest.skip("Tk is unavailable; graphical CI explicitly requires it")
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        if required:
            pytest.fail(f"FIELDFORGE_REQUIRE_GUI=1 requires a working display: {exc}")
        pytest.skip("Tk display unavailable; graphical CI explicitly requires it")
    from fieldforge.ui.online_maps import OnlineMapsTab

    root.geometry("1000x700")
    errors, panels, opened, centered, used, shown, messages = [], [], [], [], [], [], []
    root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *args, **kwargs: True)
    monkeypatch.setattr("tkinter.messagebox.showinfo", lambda *args, **kwargs: messages.append(args))
    monkeypatch.setattr("tkinter.messagebox.showerror", lambda *args, **kwargs: messages.append(args))
    monkeypatch.setattr("webbrowser.open", lambda *args, **kwargs: False)
    app = FieldForgeApp(tmp_path / "app.db")
    factory = PortalFactory(make_map(tmp_path / "fixture.mbtiles", zooms=(0,)))
    root_destroyed = False

    def destroy_parent():
        nonlocal root_destroyed
        root.destroy()
        root_destroyed = True

    def mount():
        panel = OnlineMapsTab(
            root,
            app.db.path,
            on_open_map=opened.append,
            on_center=lambda lat, lon: centered.append((lat, lon)),
            on_use_place=used.append,
            on_show_route=shown.append,
            client_factory=factory,
        )
        panels.append(panel)
        panel.pack(fill="both", expand=True)
        root.update()
        wait(root, panel)
        return panel

    try:
        yield SimpleNamespace(
            root=root, panel=mount(), app=app, factory=factory, opened=opened,
            centered=centered, used=used, shown=shown, mount=mount, messages=messages,
            destroy_parent=destroy_parent,
        )
    finally:
        for delayed in factory.delays:
            delayed.release.set()
        for panel in panels:
            if not panel._disposed:
                panel.close()
        for panel in panels:
            panel._worker.shutdown(wait=True, cancel_futures=True)
        if not root_destroyed:
            root.destroy()
        gc.collect()
    assert not errors


def wait_until(root, condition, *, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if condition():
            root.update()
            return
        time.sleep(0.005)
    pytest.fail("Timed out waiting for the portal UI")


def wait(root, panel):
    wait_until(root, lambda: not panel.busy or panel._disposed)


def pump(root, duration=0.12):
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)


def enabled(widget):
    return "disabled" not in widget.state()


def connect(screen):
    panel = screen.panel
    panel.portal_url.set("https://portal.example.invalid")
    panel.save_url_button.invoke()
    panel.connect_button.invoke()
    wait(screen.root, panel)
    assert panel.connected, panel.status.get()
    return screen.factory.clients[-1]


def search_and_select(screen, index=0):
    panel = screen.panel
    panel.query.set("Fictional address")
    panel.search_button.invoke()
    wait(screen.root, panel)
    rows = panel.results_tree.get_children()
    assert len(rows) == len(screen.factory.addresses), panel.status.get()
    panel.results_tree.selection_set(rows[index])
    panel.select_result()
    screen.root.update()
    return screen.factory.addresses[index]


def request_and_select_route(screen):
    panel = screen.panel
    panel.start_lat.set("0")
    panel.start_lon.set("0")
    panel.end_lat.set("0.01")
    panel.end_lon.set("0.01")
    panel.route_button.invoke()
    wait(screen.root, panel)
    rows = panel.route_tree.get_children()
    assert len(rows) == 2, panel.status.get()
    panel.route_tree.selection_set(rows[0])
    panel.select_route()
    screen.root.update()
    assert panel.current_route["id"] == "fictional-route-a"


def test_starts_disconnected_without_client_or_address_requests(screen):
    panel = screen.panel
    assert not screen.factory.clients
    assert not panel.connected and not panel.busy
    assert not panel.selected_result
    assert not enabled(panel.search_entry)
    assert not enabled(panel.search_button)
    assert not enabled(panel.copy_button)
    assert not panel.results_tree.get_children()
    assert screen.app.waypoints() == []
    assert panel._heartbeat_id is None
    panel._check_health()
    panel.query.set("Typing must remain local")
    panel.search()
    panel.portal_url.set("https://portal.example.invalid")
    panel.save_url_button.invoke()
    pump(screen.root)
    assert not screen.factory.clients
    assert panel._heartbeat_id is None


def test_portal_url_persists_but_reopened_tab_never_reconnects(screen):
    panel = screen.panel
    client = connect(screen)
    panel.disconnect_button.invoke()
    assert not panel.connected and not client.connected
    assert panel.portal_url.get() == "https://portal.example.invalid"
    panel.close()
    panel.destroy()
    before = list(client.calls)
    reopened = screen.mount()
    assert reopened.portal_url.get() == "https://portal.example.invalid"
    assert not reopened.connected and not reopened.busy
    assert not enabled(reopened.search_entry) and not enabled(reopened.search_button)
    assert len(screen.factory.clients) == 1 and client.calls == before


def test_environment_url_prefills_without_network_and_saved_settings_take_priority(screen, monkeypatch):
    panel = screen.panel
    panel.close()
    panel.destroy()
    monkeypatch.setenv("FIELDFORGE_MAP_PORTAL", "https://configured.example.invalid")
    reopened = screen.mount()
    assert reopened.portal_url.get() == "https://configured.example.invalid"
    assert not screen.factory.clients and not enabled(reopened.search_entry)
    reopened.portal_url.set("https://saved.example.invalid")
    reopened.save_settings()
    reopened.close()
    reopened.destroy()
    saved = screen.mount()
    assert saved.portal_url.get() == "https://saved.example.invalid"
    assert not screen.factory.clients and not saved.connected


def test_selected_coordinate_csv_saves_offline_with_source_and_refuses_overwrite(screen, tmp_path, monkeypatch):
    from fieldforge_gps.places import read_catalog

    client = connect(screen)
    panel = screen.panel
    selected = search_and_select(screen)
    panel.disconnect()
    calls = list(client.calls)
    destination = tmp_path / "selected-place.csv"
    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **_kwargs: str(destination))
    assert enabled(panel.save_place_csv_button)
    panel.save_place_csv_button.invoke()
    wait(screen.root, panel)
    assert destination.is_file(), panel.status.get()
    stored = read_catalog(destination, consent=True, wgs84_confirmed=True).places[0]
    assert (stored.latitude, stored.longitude) == (selected["latitude"], selected["longitude"])
    assert stored.name == selected["label"]
    contents = destination.read_bytes()
    for key in ("source", "attribution", "license", "retrieved_at"):
        assert selected[key].encode() in contents
    assert b"-0.00000001" in contents
    assert screen.app.waypoints() == []
    panel.save_place_csv_button.invoke()
    wait(screen.root, panel)
    assert "Could not complete save place csv" in panel.status.get()
    assert destination.read_bytes() == contents
    assert client.calls == calls and panel.selected_result == selected


def test_csv_file_picker_and_write_guard_keep_selected_coordinates_available(screen, tmp_path, monkeypatch):
    from fieldforge.ui import online_maps

    client = connect(screen)
    panel = screen.panel
    selected = search_and_select(screen)
    panel.disconnect()
    calls = list(client.calls)
    destination = tmp_path / "selected-place.csv"
    blocked, release = threading.Event(), threading.Event()
    actual_save = online_maps.save_new

    def choose(**_kwargs):
        assert not panel.can_close()
        panel._check_health()
        assert not panel.busy
        return str(destination)

    def delayed_save(path, contents):
        blocked.set()
        assert release.wait(3)
        actual_save(path, contents)

    monkeypatch.setattr(online_maps.filedialog, "asksaveasfilename", choose)
    monkeypatch.setattr(online_maps, "save_new", delayed_save)
    panel.save_place_csv_button.invoke()
    try:
        wait_until(screen.root, blocked.is_set)
        assert panel.busy and not panel.can_close()
        assert not enabled(panel.cancel_button) and not enabled(panel.save_place_csv_button)
        panel.cancel_task()
        panel.disconnect()
        assert panel.busy and panel.selected_result == selected
    finally:
        release.set()
    wait(screen.root, panel)
    assert panel.can_close() and destination.is_file(), panel.status.get()
    assert client.calls == calls


@pytest.mark.parametrize("geocoding", [False, True])
def test_address_controls_require_connected_geocoding_capability(screen, geocoding):
    screen.factory.status["geocoding"] = geocoding
    connect(screen)
    assert enabled(screen.panel.search_entry) is geocoding
    assert enabled(screen.panel.search_button) is geocoding
    screen.panel.disconnect_button.invoke()
    assert not enabled(screen.panel.search_entry)
    assert not enabled(screen.panel.search_button)


def test_typing_never_autocompletes_and_explicit_search_uses_worker(screen):
    client = connect(screen)
    panel, root = screen.panel, screen.root
    panel.query.set("One partial address")
    panel.search_entry.event_generate("<KeyRelease>")
    pump(root)
    panel.query.set("Completed fictional address")
    pump(root)
    assert not any(call[0] == "search" for call in client.calls)
    panel.search_button.invoke()
    wait(root, panel)
    calls = [call for call in client.calls if call[0] == "search"]
    assert len(calls) == 1
    assert calls[0][1] == ("Completed fictional address",)
    assert calls[0][2] != threading.get_ident()
    assert not panel.selected_result
    assert not enabled(panel.copy_button)
    assert not screen.used and screen.app.waypoints() == []


def test_selected_coordinates_keep_precision_and_work_after_disconnect(screen):
    client = connect(screen)
    panel = screen.panel
    selected = search_and_select(screen)
    assert float(panel.latitude.get()) == 0
    assert panel.longitude.get() == "-0.00000001"
    assert panel.selected_result["label"] == selected["label"]
    assert enabled(panel.copy_button) and enabled(panel.save_place_button)
    panel.disconnect_button.invoke()
    before = list(client.calls)
    panel.copy_button.invoke()
    copied = screen.root.clipboard_get()
    assert "-0.00000001" in copied and "e-" not in copied.lower()
    panel.use_start()
    panel.use_destination()
    assert float(panel.start_lat.get()) == float(panel.end_lat.get()) == 0
    assert panel.start_lon.get() == panel.end_lon.get() == "-0.00000001"
    panel.center_map()
    panel.save_place_button.invoke()
    assert screen.centered == [(0.0, -0.00000001)]
    assert screen.used == [selected]
    assert screen.app.waypoints() == []  # Prefill is not an implicit database save.
    assert client.calls == before


def test_offline_address_prefills_real_place_editor_and_saves_only_on_request(screen):
    from fieldforge.navigation.places import PlaceStore

    client = connect(screen)
    panel, root = screen.panel, screen.root
    selected = search_and_select(screen)
    panel.disconnect_button.invoke()
    calls = list(client.calls)
    panel.on_use_place = None
    panel.save_place_button.invoke()
    root.update()
    editor = panel.dialog
    assert editor is not None
    assert editor.fields["name"].get() == selected["label"]
    assert float(editor.fields["latitude"].get()) == 0
    assert editor.fields["longitude"].get() == "-0.00000001"
    notes = editor.note.get("1.0", "end-1c")
    for key in ("source", "attribution", "license", "retrieved_at"):
        assert selected[key] in notes
    assert screen.app.waypoints() == []
    editor.save_button.invoke()
    root.update()
    assert panel.dialog is None
    records = PlaceStore(screen.app.db.path).snapshot().records
    assert len(records) == 1
    point = records[0].point
    assert point.name == selected["label"]
    assert point.latitude == 0 and point.longitude == -0.00000001
    for key in ("source", "attribution", "license", "retrieved_at"):
        assert selected[key] in point.notes
    assert not screen.used and client.calls == calls


def test_failed_search_preserves_explicitly_selected_coordinates(screen):
    from fieldforge.online.client import PortalOffline

    client = connect(screen)
    panel = screen.panel
    selected = search_and_select(screen, 1)
    client.errors["search"] = PortalOffline("Fictional portal is unreachable")
    panel.query.set("Second address request")
    panel.search_button.invoke()
    wait(screen.root, panel)
    assert panel.selected_result == selected
    assert panel.latitude.get() == "1.25" and panel.longitude.get() == "2.5"
    assert enabled(panel.copy_button) and enabled(panel.save_place_button)
    assert not panel.connected
    assert not enabled(panel.search_entry) and not enabled(panel.search_button)
    assert "unreachable" in panel.status.get().lower()


def test_periodic_health_failure_disables_search_and_preserves_selected_coordinates(screen):
    from fieldforge.online.client import PortalOffline

    client = connect(screen)
    panel, root = screen.panel, screen.root
    selected = search_and_select(screen, 1)
    delayed = client.delay("connect")
    client.errors["connect"] = PortalOffline("Health check lost the portal connection")
    panel._schedule_health(20)
    wait_until(root, delayed.started.is_set)
    assert panel.busy and not enabled(panel.search_button)
    delayed.release.set()
    wait(root, panel)
    assert not panel.connected and not client.connected
    assert not enabled(panel.search_entry) and not enabled(panel.search_button)
    assert panel.selected_result == selected and enabled(panel.copy_button)
    assert panel._heartbeat_id is None
    calls = list(client.calls)
    panel._check_health()
    pump(root, duration=0.25)
    assert client.calls == calls


def test_download_opens_completed_file_and_remains_in_local_catalog(screen):
    client = connect(screen)
    panel, root = screen.panel, screen.root
    panel.refresh_catalog()
    wait(root, panel)
    rows = panel.maps_tree.get_children()
    assert len(rows) == 1
    panel.maps_tree.selection_set(rows[0])
    root.update()
    delayed = client.delay("download")
    panel.download_selected()
    wait_until(root, delayed.started.is_set)
    assert panel.busy and not screen.opened
    heartbeats = []
    root.after(5, lambda: heartbeats.append(True))
    wait_until(root, lambda: bool(heartbeats))
    assert not delayed.finished.is_set()
    delayed.release.set()
    wait(root, panel)
    assert len(screen.opened) == 1, panel.status.get()
    downloaded = Path(screen.opened[0])
    rows = panel.local_maps_tree.get_children()
    assert len(rows) == 1, panel.status.get()
    panel.disconnect_button.invoke()
    calls = list(client.calls)
    panel.local_maps_tree.selection_set(rows[0])
    root.update()
    panel.open_map_button.invoke()
    assert screen.opened == [downloaded, downloaded], panel.status.get()
    assert downloaded.name == screen.factory.asset["filename"]
    assert hashlib.sha256(downloaded.read_bytes()).hexdigest() == screen.factory.asset["sha256"]
    panel.refresh_local()
    wait(root, panel)
    assert panel.local_maps_tree.get_children()
    assert downloaded.exists() and client.calls == calls


def test_route_save_reopen_and_gpx_export_do_not_need_connection(screen, tmp_path, monkeypatch):
    client = connect(screen)
    panel, root = screen.panel, screen.root
    request_and_select_route(screen)
    route = dict(panel.current_route)
    assert "Fictional Test Road" in panel.route_steps.get("1.0", "end")
    panel.save_route_button.invoke()
    wait(root, panel)
    panel.refresh_local()
    wait(root, panel)
    assert panel.saved_routes_tree.get_children(), panel.status.get()
    panel.disconnect_button.invoke()
    panel.close()
    panel.destroy()
    calls = list(client.calls)
    reopened = screen.mount()
    rows = reopened.saved_routes_tree.get_children()
    assert len(rows) == 1
    reopened.saved_routes_tree.selection_set(rows[0])
    root.update()
    reopened.open_saved_route()
    wait(root, reopened)
    assert reopened.current_route == route
    assert "Fictional Test Road" in reopened.route_steps.get("1.0", "end")
    assert enabled(reopened.export_gpx_button)
    reopened.show_route_button.invoke()
    assert screen.shown == [route]
    target = tmp_path / "planned-route.gpx"
    monkeypatch.setattr(
        "fieldforge.ui.online_maps.filedialog.asksaveasfilename", lambda **kwargs: str(target)
    )
    reopened.export_gpx_button.invoke()
    wait(root, reopened)
    document = ET.fromstring(target.read_bytes())
    points = [element for element in document.iter() if element.tag.rsplit("}", 1)[-1] in {"rtept", "trkpt"}]
    assert [(float(point.attrib["lon"]), float(point.attrib["lat"])) for point in points] == [
        tuple(point) for point in route["geometry"]
    ]
    assert not any(element.tag.rsplit("}", 1)[-1] == "time" for point in points for element in point)
    assert "planned-route" in target.read_text(encoding="utf-8")
    assert len(screen.factory.clients) == 1 and client.calls == calls


def test_route_without_turn_steps_shows_geometry_without_inventing_directions(screen):
    connect(screen)
    screen.factory.routes = tuple(dict(route, steps=[]) for route in screen.factory.routes)
    panel = screen.panel
    request_and_select_route(screen)
    assert "No turn instructions supplied" in panel.route_info.get()
    details = panel.route_steps.get("1.0", "end")
    assert "This route has no supplied turn instructions." in details
    assert "3 route geometry points included in this plan." in details
    assert "included with these directions" not in details
    panel.disconnect()
    panel.save_route_button.invoke()
    wait(screen.root, panel)
    assert panel.saved_routes_tree.get_children()
    assert panel.current_route["steps"] == []
    panel.show_route_button.invoke()
    assert screen.shown[-1]["geometry"] == screen.factory.routes[0]["geometry"]


def test_browser_downloaded_route_imports_and_reopens_fully_offline(screen, tmp_path, monkeypatch):
    panel, root = screen.panel, screen.root
    route = screen.factory.routes[0]
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    source = downloads / "browser-downloaded-route.json"
    source.write_bytes(json.dumps({
        "schema_version": 1,
        "kind": "planned-route",
        "saved_at": "2026-10-04T00:00:00Z",
        "route": route,
    }, indent=2).encode("utf-8"))
    original_bytes = source.read_bytes()
    assert not source.is_relative_to(panel.library.root)
    assert not screen.factory.clients and not panel.connected
    assert enabled(panel.import_route_button)
    import_threads = []
    original_import = panel.library.import_route

    def record_import(path):
        import_threads.append(threading.get_ident())
        return original_import(path)

    monkeypatch.setattr(panel.library, "import_route", record_import)
    monkeypatch.setattr(
        "fieldforge.ui.online_maps.filedialog.askopenfilename", lambda **kwargs: str(source)
    )
    panel.tabs.select(panel.routes_tab)
    root.update()
    panel.import_route_button.invoke()
    wait(root, panel)
    assert import_threads and all(thread != threading.get_ident() for thread in import_threads)
    assert source.read_bytes() == original_bytes
    assert panel.current_route == route, panel.status.get()
    assert route["title"] in panel.route_info.get()
    directions = panel.route_steps.get("1.0", "end")
    assert all(step["instruction"] in directions for step in route["steps"])
    assert route["source"] in directions and route["license"] in directions
    saved = panel.library.routes()
    assert len(saved) == 1 and len(panel.saved_routes_tree.get_children()) == 1
    assert saved[0] != source and saved[0].parent == panel.library.routes_directory
    assert panel.library.load_route(saved[0]) == route
    panel.close()
    panel.destroy()
    reopened = screen.mount()
    rows = reopened.saved_routes_tree.get_children()
    assert len(rows) == 1
    reopened.saved_routes_tree.selection_set(rows[0])
    root.update()
    reopened.open_route_button.invoke()
    wait(root, reopened)
    assert reopened.current_route == route
    reopened_directions = reopened.route_steps.get("1.0", "end")
    assert all(step["instruction"] in reopened_directions for step in route["steps"])
    assert source.read_bytes() == original_bytes
    assert not screen.factory.clients and not reopened.connected


def test_corrupt_browser_route_import_preserves_previous_selection_and_saved_files(screen, tmp_path):
    panel, root = screen.panel, screen.root
    route = screen.factory.routes[0]
    saved = panel.library.save_route(route)
    panel.open_route_path(saved)
    wait(root, panel)
    panel.refresh_local()
    wait(root, panel)
    prior_rows = tuple(panel.saved_routes_tree.item(row, "values") for row in panel.saved_routes_tree.get_children())
    prior_files = {path: path.read_bytes() for path in panel.library.routes()}
    prior_summary = panel.route_info.get()
    prior_directions = panel.route_steps.get("1.0", "end")
    source = tmp_path / "corrupted-browser-download.json"
    corrupted = b'{"schema_version": 1, "kind": "planned-route", "route": '
    source.write_bytes(corrupted)
    panel.import_route_path(source)
    wait(root, panel)
    assert panel.current_route == route
    assert prior_summary in panel.route_info.get()
    assert panel.route_steps.get("1.0", "end") == prior_directions
    assert tuple(panel.saved_routes_tree.item(row, "values") for row in panel.saved_routes_tree.get_children()) == prior_rows
    assert {path: path.read_bytes() for path in panel.library.routes()} == prior_files
    assert source.read_bytes() == corrupted
    assert "import" in panel.status.get().lower() and "invalid" in panel.status.get().lower()
    assert all(enabled(button) for button in (
        panel.import_route_button, panel.save_route_button,
        panel.show_route_button, panel.export_gpx_button,
    ))
    assert not screen.factory.clients and not panel.connected


@pytest.mark.parametrize("change", ["manual", "use_destination"])
def test_changed_endpoint_labels_retained_plan_and_selection_restores_match(screen, change):
    client = connect(screen)
    panel, root = screen.panel, screen.root
    request_and_select_route(screen)
    previous = dict(panel.current_route)
    previous_directions = panel.route_steps.get("1.0", "end")
    mismatch = "Selected plan uses previous coordinates"
    endpoints = ("Start: latitude 0.0, longitude 0.0", "Destination: latitude 0.01, longitude 0.01")
    assert mismatch not in panel.route_info.get()
    for text in endpoints:
        assert text in panel.route_info.get() and text in previous_directions

    if change == "manual":
        panel.tabs.select(panel.routes_tab)
        root.update()
        entry = next(widget for container in panel.routes_tab.winfo_children()
                     for widget in container.winfo_children()
                     if widget.winfo_class() == "TEntry" and
                     str(widget.cget("textvariable")) == str(panel.end_lat))
        entry.delete(0, "end")
        assert mismatch in panel.route_info.get().splitlines()
        entry.insert(0, "0.02")
    else:
        selected = search_and_select(screen, 1)
        panel.destination_button.invoke()
        assert float(panel.end_lat.get()) == selected["latitude"]
        assert float(panel.end_lon.get()) == selected["longitude"]
    root.update()
    assert mismatch in panel.route_info.get().splitlines()
    assert panel.current_route == previous
    assert panel.route_steps.get("1.0", "end") == previous_directions
    assert all(text in panel.route_info.get() for text in endpoints)
    assert all(enabled(button) for button in (
        panel.save_route_button, panel.export_gpx_button, panel.show_route_button,
    ))
    calls = list(client.calls)
    panel.save_route_button.invoke()
    wait(root, panel)
    saved = panel.library.routes()
    assert len(saved) == 1 and panel.library.load_route(saved[0]) == previous
    assert mismatch in panel.route_info.get().splitlines()
    assert client.calls == calls

    publications = []
    token = panel.route_info.trace_add("write", lambda *_: publications.append(panel.route_info.get()))
    try:
        panel.route_tree.selection_set(panel.route_tree.get_children()[1])
        root.update()
    finally:
        panel.route_info.trace_remove("write", token)
    assert panel.current_route == screen.factory.routes[1]
    assert publications and all(mismatch not in value for value in publications)
    assert [float(value.get()) for value in (panel.start_lat, panel.start_lon, panel.end_lat, panel.end_lon)] == [
        0.0, 0.0, 0.01, 0.01,
    ]
    assert all(text in panel.route_info.get() for text in endpoints)


def test_each_endpoint_tracks_changes_and_accepts_equivalent_decimal_spelling(screen):
    connect(screen)
    panel = screen.panel
    request_and_select_route(screen)
    previous = dict(panel.current_route)
    mismatch = "Selected plan uses previous coordinates"
    for value, equivalent in ((panel.start_lat, "+0.000"), (panel.start_lon, "-0.0"),
                              (panel.end_lat, ".0100"), (panel.end_lon, "0.01000")):
        value.set("1.25")
        assert mismatch in panel.route_info.get().splitlines()
        value.set(equivalent)
        assert mismatch not in panel.route_info.get()
        assert panel.current_route == previous


@pytest.mark.parametrize("outcome", ["alternatives", "empty", "failure", "disconnect"])
def test_new_route_response_requires_selection_but_failure_retains_prior_route(screen, outcome):
    from fieldforge.online.client import PortalError

    client = connect(screen)
    panel, root = screen.panel, screen.root
    request_and_select_route(screen)
    previous = dict(panel.current_route)
    previous_summary = panel.route_info.get()
    previous_directions = panel.route_steps.get("1.0", "end")
    previous_rows = panel.route_tree.get_children()
    actions = (panel.save_route_button, panel.show_route_button, panel.export_gpx_button)
    assert all(enabled(button) for button in actions)
    replacement = dict(
        previous,
        id="fictional-replacement-route",
        title="Fictional replacement destination",
        geometry=[[0.0, 0.0], [0.01, 0.015], [0.02, 0.02]],
        end={"latitude": 0.02, "longitude": 0.02},
        steps=[dict(previous["steps"][0], instruction="Use Replacement Test Road.")],
    )
    screen.factory.routes = () if outcome == "empty" else (replacement,)
    panel.end_lat.set("0.02")
    panel.end_lon.set("0.02")
    mismatch = "Selected plan uses previous coordinates"
    assert mismatch in panel.route_info.get().splitlines()
    if outcome == "failure":
        client.errors["routes"] = PortalError("The replacement route could not be calculated")
    delayed = client.delay("routes") if outcome == "disconnect" else None
    panel.route_button.invoke()
    if delayed is not None:
        wait_until(root, delayed.started.is_set)
        panel.disconnect_button.invoke()
        assert delayed.cancel is not None and delayed.cancel.is_set()
        delayed.release.set()
        wait_until(root, delayed.finished.is_set)
        pump(root)
    else:
        wait(root, panel)

    if outcome in {"failure", "disconnect"}:
        assert panel.current_route == previous
        assert previous_summary in panel.route_info.get()
        reason = ("Previous selection retained; new route request failed." if outcome == "failure" else
                  "Selected route remains available offline.")
        assert mismatch in panel.route_info.get().splitlines()
        assert reason in panel.route_info.get()
        panel.start_lon.set("0.005")
        assert mismatch in panel.route_info.get().splitlines()
        assert reason in panel.route_info.get()
        assert panel.route_steps.get("1.0", "end") == previous_directions
        assert panel.route_tree.get_children() == previous_rows
        assert all(enabled(button) for button in actions)
        assert panel.connected is (outcome == "failure")
        panel.show_route_button.invoke()
        assert screen.shown == [previous]
        return

    assert panel.current_route is None
    assert mismatch not in panel.route_info.get()
    assert previous["title"] not in panel.route_info.get()
    directions = panel.route_steps.get("1.0", "end")
    assert all(step["instruction"] not in directions for step in previous["steps"])
    assert not panel.route_tree.selection()
    assert all(not enabled(button) for button in actions)
    panel.show_route_button.invoke()
    assert not screen.shown
    rows = panel.route_tree.get_children()
    assert len(rows) == (0 if outcome == "empty" else 1)
    if rows:
        panel.route_tree.selection_set(rows[0])
        panel.select_route()
        root.update()
        assert panel.current_route == replacement
        assert replacement["title"] in panel.route_info.get()
        assert mismatch not in panel.route_info.get()
        assert "Destination: latitude 0.02, longitude 0.02" in panel.route_info.get()
        assert "Use Replacement Test Road." in panel.route_steps.get("1.0", "end")
        assert all(enabled(button) for button in actions)
        panel.show_route_button.invoke()
        assert screen.shown == [replacement]


def test_disconnect_discards_late_search_without_losing_selected_place(screen):
    client = connect(screen)
    panel, root = screen.panel, screen.root
    selected = search_and_select(screen, 1)
    delayed = client.delay("search")
    panel.query.set("A slow replacement address")
    panel.search_button.invoke()
    wait_until(root, delayed.started.is_set)
    panel.disconnect_button.invoke()
    assert not panel.connected
    assert delayed.cancel is not None and delayed.cancel.is_set()
    status = panel.status.get()
    delayed.release.set()
    wait_until(root, delayed.finished.is_set)
    pump(root)
    assert not panel.busy and not panel.connected
    assert panel.selected_result == selected
    assert panel.status.get() == status
    assert not enabled(panel.search_entry) and not enabled(panel.search_button)


def test_close_cancels_pending_download_and_ignores_late_open_callback(screen):
    client = connect(screen)
    panel, root = screen.panel, screen.root
    panel.refresh_catalog()
    wait(root, panel)
    panel.maps_tree.selection_set(panel.maps_tree.get_children()[0])
    root.update()
    delayed = client.delay("download")
    panel.download_selected()
    wait_until(root, delayed.started.is_set)
    endpoint_traces = list(panel._route_endpoint_traces)
    assert len(endpoint_traces) == 4
    panel.close()
    assert panel._disposed
    assert all(token not in {callback for _mode, callback in value.trace_info()}
               for value, token in endpoint_traces)
    assert delayed.cancel is not None and delayed.cancel.is_set()
    panel.destroy()
    delayed.release.set()
    wait_until(root, delayed.finished.is_set)
    pump(root)
    assert not screen.opened


def test_parent_destroy_cancels_pending_search_without_touching_destroyed_tk(screen):
    client = connect(screen)
    panel, root = screen.panel, screen.root
    delayed = client.delay("search")
    panel.query.set("A request still pending when the parent closes")
    panel.search_button.invoke()
    wait_until(root, delayed.started.is_set)
    endpoint_traces = list(panel._route_endpoint_traces)
    assert len(endpoint_traces) == 4
    screen.destroy_parent()
    assert panel._disposed and not client.connected
    assert all(token not in {callback for _mode, callback in value.trace_info()}
               for value, token in endpoint_traces)
    assert delayed.cancel is not None and delayed.cancel.is_set()
    delayed.release.set()
    assert delayed.finished.wait(1)
    panel._worker.shutdown(wait=True, cancel_futures=True)
    assert not panel.selected_result and not panel._results
    assert not screen.opened and not screen.used


def test_close_removes_all_owned_traces_and_destroy_releases_tk_references(screen, monkeypatch):
    import tkinter as tk
    import weakref

    client = connect(screen)
    panel, root = screen.panel, screen.root
    search_and_select(screen, 1)
    request_and_select_route(screen)
    panel.refresh_catalog()
    wait(root, panel)
    panel.maps_tree.selection_set(panel.maps_tree.get_children()[0])
    panel.select_map()
    root.update()
    selected, route = panel.selected_result, panel.current_route
    results, routes, worker = panel._results, panel._routes, panel._worker
    variables = {name: value for name, value in vars(panel).items() if isinstance(value, tk.Variable)}
    traced = {name for name, value in variables.items() if value.trace_info()}
    assert traced == {"start_lat", "start_lon", "end_lat", "end_lon", "selected_info", "map_info"}
    variables.update({"filters." + name: value for name, value in vars(panel.catalog_filters).items()
                      if isinstance(value, tk.Variable)})
    references = {id(value): weakref.ref(value) for value in variables.values()}
    expected = {
        (id(variable), callback)
        for variable in variables.values()
        for _modes, callback in variable.trace_info()
    }
    removals = []
    finalizers = []
    remove = tk.Variable.trace_remove
    finalize = tk.Variable.__del__
    ui_thread = threading.get_ident()

    def record_removal(variable, modes, callback):
        removals.append((id(variable), callback, threading.get_ident()))
        return remove(variable, modes, callback)

    def record_finalization(variable):
        identity = id(variable)
        if identity in references:
            finalizers.append((identity, threading.get_ident()))
        return finalize(variable)

    monkeypatch.setattr(tk.Variable, "trace_remove", record_removal)
    monkeypatch.setattr(tk.Variable, "__del__", record_finalization)
    panel.close()
    assert panel._disposed and not client.connected
    assert panel._route_endpoint_traces == []
    assert all(not variable.trace_info() for variable in variables.values())
    assert expected <= {(identity, callback) for identity, callback, _thread in removals}
    assert removals and all(thread == ui_thread for _identity, _callback, thread in removals)
    panel.destroy()
    root.update()

    # Inspect owned references without asking another thread to collect live Tk
    # objects. Keeping these variables here lets us verify removal safely on Tk's
    # thread; application-owned containers must release their references too.
    leaks, visited = [], set()

    def inspect(value, path):
        if isinstance(value, (tk.Variable, tk.Misc)):
            leaks.append((path, type(value).__name__))
            return
        if id(value) in visited:
            return
        visited.add(id(value))
        if isinstance(value, dict):
            for key, child in value.items():
                inspect(child, f"{path}[{key!r}]")
        elif isinstance(value, (tuple, list, set, frozenset)):
            for index, child in enumerate(value):
                inspect(child, f"{path}[{index}]")

    for name, value in vars(panel).items():
        if name not in {"master", "children", "tk", "_tclCommands"}:
            inspect(value, name)
    del name, value
    assert leaks == []
    assert all(not variable.trace_info() for variable in variables.values())
    assert panel._route_endpoint_traces == []
    assert panel.selected_result is selected and panel.current_route is route
    assert panel._results is results and panel._routes is routes
    assert panel._worker is worker and panel._disposed
    variables.clear()
    assert all(reference() is None for reference in references.values())
    assert {identity for identity, _thread in finalizers} == references.keys()
    assert all(thread == ui_thread for _identity, thread in finalizers)


def test_minimum_geometry_keeps_online_and_offline_controls_visible(screen):
    panel, root = screen.panel, screen.root
    root.geometry("1000x700")
    root.update()
    right = panel.winfo_rootx() + panel.winfo_width()
    bottom = panel.winfo_rooty() + panel.winfo_height()
    groups = (
        (panel.address_tab, (
            panel.search_entry, panel.search_button, panel.results_tree,
            panel.copy_button, panel.save_place_button, panel.save_place_csv_button, panel.center_button,
        )),
        (panel.maps_tab, (
            panel.refresh_catalog_button, panel.download_button,
            panel.maps_tree, panel.local_maps_tree, panel.open_map_button,
        )),
        (panel.routes_tab, (
            panel.route_button, panel.save_route_button, panel.open_route_button,
            panel.export_gpx_button, panel.show_route_button, panel.import_route_button,
            panel.saved_routes_tree, panel.route_steps,
        )),
    )
    for tab, widgets in groups:
        panel.tabs.select(tab)
        root.update()
        for widget in (panel.connect_button, panel.disconnect_button, panel.footer, *widgets):
            assert widget.winfo_ismapped(), widget
            assert widget.winfo_rootx() >= panel.winfo_rootx(), widget
            assert widget.winfo_rooty() >= panel.winfo_rooty(), widget
            assert widget.winfo_rootx() + widget.winfo_width() <= right, widget
            assert widget.winfo_rooty() + widget.winfo_height() <= bottom, widget


def test_connection_cancel_has_no_requests_and_confirm_opens_only_on_connect(screen, monkeypatch):
    panel = screen.panel
    launches, prompts = [], []
    panel.portal_url.set("https://portal.example.invalid")
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *args, **kwargs: prompts.append((args, kwargs)) or False)
    monkeypatch.setattr("webbrowser.open", lambda url, **kwargs: launches.append(url) or False)
    panel.connect_button.invoke()
    assert prompts and not launches and not panel.connected
    assert not any(client.calls for client in screen.factory.clients)
    assert "Stayed offline" in panel.status.get()
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *args, **kwargs: True)
    client = connect(screen)
    assert launches == ["https://portal.example.invalid"]
    assert "Copy portal link" in panel.status.get()
    panel.copy_portal_link()
    assert panel.clipboard_get() == "https://portal.example.invalid"
    panel._complete("health", client.capabilities)
    assert len(launches) == 1
    panel.disconnect()
    panel.open_portal_home()
    assert len(launches) == 1


def test_filters_preserve_download_identity_and_work_offline(screen):
    client = connect(screen)
    panel = screen.panel
    north = dict(screen.factory.asset, id="north", title="Éclair North", coverage="North region",
                 filename="north.mbtiles", download_path="/api/v1/maps/north/download")
    south = dict(screen.factory.asset, id="south", title="Bay South", coverage="South region",
                 filename="south.mbtiles", download_path="/api/v1/maps/south/download")
    client.catalog = lambda **kwargs: (north, south)
    panel.refresh_catalog()
    wait(screen.root, panel)
    assert panel.maps_tree.get_children() == ("1", "0")
    panel.maps_tree.selection_set("1")
    panel.catalog_filters.query.set("north eclair")
    assert panel.maps_tree.get_children() == ("0",)
    assert not panel.maps_tree.selection() and not enabled(panel.download_button)
    panel.maps_tree.selection_set("0")
    panel.select_map()
    panel.download_selected()
    wait(screen.root, panel)
    downloaded = [call for call in client.calls if call[0] == "download"]
    assert downloaded[0][1][0]["id"] == "north"
    assert screen.opened[-1].name == "north.mbtiles"
    panel.disconnect()
    before = list(client.calls)
    panel.catalog_filters.query.set("south")
    assert panel.maps_tree.get_children() == ("1",)
    assert not enabled(panel.download_button)
    panel.catalog_filters.kind.set("Images")
    assert not panel.maps_tree.get_children()
    assert "no matches" in panel.catalog_filters.count.get()
    assert client.calls == before


def _two_list_maps(screen, client):
    maps = tuple(dict(screen.factory.asset, id=key, title=key.title(), filename=key + ".mbtiles",
                      download_path=f"/api/v1/maps/{key}/download") for key in ("north", "south"))
    client.catalog = lambda **kwargs: maps
    screen.panel.refresh_catalog()
    wait(screen.root, screen.panel)
    return maps


def test_download_list_survives_filters_and_offline_export_import(screen, tmp_path, monkeypatch):
    client = connect(screen)
    panel = screen.panel
    maps = _two_list_maps(screen, client)
    for index in range(2):
        panel.maps_tree.selection_set(str(index))
        screen.root.update()
        panel.add_to_list_button.invoke()
    assert len(panel._download_list["maps"]) == 2
    assert panel._download_list["total_bytes"] == sum(item["bytes"] for item in maps)
    panel.catalog_filters.query.set("not present")
    assert len(panel._download_list["maps"]) == 2
    panel.disconnect()
    before = list(client.calls)
    panel.review_list_button.invoke()
    window = panel._download_list_window
    assert window.tree.get_children() == ("north", "south")
    assert not enabled(window.download_button)
    target = tmp_path / "offline-list.json"
    monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **kwargs: str(target))
    window.save_button.invoke()
    wait(screen.root, panel)
    assert target.exists()
    window.clear_button.invoke()
    assert panel._download_list is None
    monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **kwargs: str(target))
    window.import_button.invoke()
    wait(screen.root, panel)
    assert len(panel._download_list["maps"]) == 2 and not panel.connected
    assert client.calls == before
    assert "2 maps" in window.info.get()
    window.tree.selection_set("north")
    window.remove()
    assert [item["id"] for item in panel._download_list["maps"]] == ["south"]
    window.close()
    assert panel._download_list_window is None


def test_download_list_batch_reuses_files_without_opening_every_map(screen):
    client = connect(screen)
    panel = screen.panel
    _two_list_maps(screen, client)
    for index in range(2):
        panel.maps_tree.selection_set(str(index))
        panel.add_to_download_list()
    panel.review_download_list()
    window = panel._download_list_window
    assert enabled(window.download_button)
    window.download_button.invoke()
    wait(screen.root, panel)
    assert len(panel._local_maps) == 2, panel.status.get()
    assert not screen.opened
    assert "ready offline" in panel.status.get()
    assert len([call for call in client.calls if call[0] == "download"]) == 2
    assert client.last_resume is True
    window.download_button.invoke()
    wait(screen.root, panel)
    assert len([call for call in client.calls if call[0] == "download"]) == 2
    assert enabled(window.remove_button) is False


def test_invalid_list_import_preserves_selection_and_does_not_switch_portals(screen, tmp_path, monkeypatch):
    from fieldforge.online.download_list import make_download_list, save_download_list

    client = connect(screen)
    panel = screen.panel
    maps = _two_list_maps(screen, client)
    panel.maps_tree.selection_set("0")
    panel.add_to_download_list()
    original = panel._download_list
    broken = tmp_path / "broken.json"
    broken.write_text('{"kind":"not a list"}')
    monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **kwargs: str(broken))
    panel.import_download_list()
    wait(screen.root, panel)
    assert panel._download_list is original
    foreign = tmp_path / "foreign.json"
    save_download_list(make_download_list("https://other.example.invalid", list(maps)), foreign)
    monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **kwargs: str(foreign))
    before = list(client.calls)
    panel.import_download_list()
    wait(screen.root, panel)
    panel.review_download_list()
    assert not enabled(panel._download_list_window.download_button)
    panel.download_list()
    assert "portal named" in panel.status.get()
    panel._download_list_window.copy_portal_button.invoke()
    assert panel.clipboard_get() == "https://other.example.invalid"
    assert panel.portal_url.get() == "https://portal.example.invalid"
    assert client.calls == before


def test_download_list_cancel_drops_late_completion_and_retains_selection(screen):
    client = connect(screen)
    panel = screen.panel
    _two_list_maps(screen, client)
    panel.maps_tree.selection_set("0")
    panel.add_to_download_list()
    selected = panel._download_list
    delayed = client.delay("download")
    panel.review_download_list()
    panel.download_list()
    wait_until(screen.root, delayed.started.is_set)
    assert enabled(panel._download_list_window.stop_button)
    assert not enabled(panel._download_list_window.clear_button)
    panel.cancel_task()
    assert delayed.cancel.is_set()
    delayed.release.set()
    wait(screen.root, panel)
    assert panel._download_list is selected and not screen.opened
    assert "stopped" in panel.status.get()


def test_download_list_window_releases_its_tk_variables_on_parent_destruction(screen):
    import weakref

    panel = screen.panel
    panel.review_download_list()
    window = panel._download_list_window
    variable = weakref.ref(window.info)
    keep_partial = weakref.ref(panel.keep_partial_maps)
    panel.destroy()
    screen.root.update()
    assert panel._download_list_window is None
    assert variable() is None
    assert keep_partial() is None
    assert window.owner is None


def test_download_list_resume_option_can_be_disabled(screen):
    client = connect(screen)
    panel = screen.panel
    _two_list_maps(screen, client)
    panel.maps_tree.selection_set("0")
    panel.add_to_download_list()
    panel.review_download_list()
    panel._download_list_window.resume_button.invoke()
    assert panel.keep_partial_maps.get() is False
    panel.download_list()
    wait(screen.root, panel)
    assert client.last_resume is False and len(panel._local_maps) == 1


def test_partial_discard_is_offline_confirmed_and_preserves_completed_maps(screen, monkeypatch):
    from fieldforge.online.partial_download import PartialDownload

    client = connect(screen)
    panel = screen.panel
    _two_list_maps(screen, client)
    panel.maps_tree.selection_set("0")
    panel.add_to_download_list()
    panel.download_list()
    wait(screen.root, panel)
    document = panel._download_list
    target = panel._local_maps[0]
    original = target.read_bytes()
    with PartialDownload(target, document["maps"][0], document["portal"]) as partial:
        partial.prepare(lambda: None)
        partial.append(original[:20])
        partial.checkpoint()
    panel.disconnect()
    wait(screen.root, panel)
    panel.review_download_list()
    window = panel._download_list_window
    calls = list(client.calls)
    assert enabled(window.discard_button) and not enabled(window.download_button)
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *args, **kwargs: False)
    window.discard_button.invoke()
    assert partial.path.exists() and partial.note.exists()
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda *args, **kwargs: True)
    window.discard_button.invoke()
    wait(screen.root, panel)
    assert not partial.path.exists() and not partial.note.exists()
    assert target.read_bytes() == original and panel._download_list is document
    assert client.calls == calls and not panel.connected
    assert "Discarded" in panel.status.get()


def test_download_list_transfer_controls_fit_minimum_window(screen):
    panel = screen.panel
    panel.review_download_list()
    window = panel._download_list_window
    window.geometry("720x500")
    panel.transfer_info.set("999.9 MiB / 999.9 MiB")
    screen.root.update()
    for control in (window.resume_button, window.discard_button, window.download_button, window.stop_button,
                    window.import_button, window.copy_portal_button):
        assert control.winfo_ismapped()
        assert control.winfo_rootx() >= window.winfo_rootx()
        assert control.winfo_rootx() + control.winfo_width() <= window.winfo_rootx() + window.winfo_width()
        assert control.winfo_rooty() + control.winfo_height() <= window.winfo_rooty() + window.winfo_height()
