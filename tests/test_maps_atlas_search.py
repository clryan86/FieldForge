"""Main-tab town discovery with real bundled data and asynchronous Tk workers."""
import socket
import threading
import time

import pytest
import test_maps_ui
from test_route_overlay_ui import planned_route

from fieldforge.ui import atlas_search
from fieldforge_gps.bundled_atlas import map_path, places_path

screen = test_maps_ui.screen
opened = test_maps_ui.opened
wait = test_maps_ui.wait


@pytest.fixture
def towns_screen(screen, monkeypatch):
    workers = []
    worker_class = atlas_search.LatestPlaceWorker

    def tracked_worker():
        worker = worker_class()
        workers.append(worker)
        return worker

    monkeypatch.setattr(atlas_search, "LatestPlaceWorker", tracked_worker)
    yield screen
    screen[1].close_atlas_search()
    for worker in workers:
        worker._thread.join(2)
        assert not worker._thread.is_alive(), "Included-town finder leaked its worker"


def settle_finder(root, finder):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        root.update()
        if finder._job is None:
            return
        time.sleep(.005)
    pytest.fail(f"Included-town finder did not finish: {finder.status.get()}")


def search(context, query):
    root, panel, _, _ = context
    panel.open_atlas_search()
    finder = panel._atlas_search
    settle_finder(root, finder)
    finder.query.set(query)
    finder.search_button.invoke()
    settle_finder(root, finder)
    return finder


def select(root, finder, name):
    index = next(i for i, place in enumerate(finder._results) if place.name == name)
    finder.table.selection_set(str(index))
    root.update()
    return finder._results[index]


def test_main_maps_search_opens_real_town_offline_without_private_reads(towns_screen, monkeypatch):
    root, panel, app, _ = towns_screen
    before = app.db.path.read_bytes()
    catalogue_before = places_path().read_bytes()

    def forbidden(*_args, **_kwargs):
        pytest.fail("Included-town search attempted network or private-place access")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr("fieldforge.ui.maps.read_markers", forbidden)
    assert str(panel.atlas_search_button["state"]) == "normal"
    panel.atlas_search_button.invoke()
    finder = panel._atlas_search
    settle_finder(root, finder)
    assert finder.catalog is not None and finder.table.get_children()
    assert len(finder._results) <= 100
    assert panel.pack_info is None and panel._included_place is None
    assert not finder.table.selection()
    assert not finder.show_selected()
    finder = search(towns_screen, "Tulsa")
    place = select(root, finder, "Tulsa")
    assert "Natural Earth" in finder.detail.get()
    finder.show_button.invoke()
    wait(root, panel)
    assert panel.pack_info.path == map_path().resolve()
    assert panel.view.latitude == pytest.approx(place.latitude)
    assert panel.view.longitude == pytest.approx(place.longitude)
    assert panel._images and panel.canvas.find_withtag("included-town-marker")
    assert "Tulsa" in panel.public_place_status.get()
    assert "no street detail" in panel.public_place_status.get().lower()
    assert "Natural Earth" in panel.attribution.get()
    assert not panel.overlay.get() and not panel.markers
    assert app.db.path.read_bytes() == before
    assert places_path().read_bytes() == catalogue_before
    assert panel._atlas_window.state() == "withdrawn"
    panel.open_atlas_search()
    root.update()
    assert panel._atlas_search is finder and panel._atlas_window.state() == "normal"


def test_query_edits_clear_selection_and_missing_names_are_honest(towns_screen):
    root, panel, _, _ = towns_screen
    finder = search(towns_screen, "Tulsa")
    select(root, finder, "Tulsa")
    finder.query.set("Honolulu")
    assert not finder._results and not finder.table.selection()
    assert str(finder.show_button["state"]) == "disabled"
    assert not finder.show_selected() and panel.pack_info is None
    finder.search_button.invoke()
    settle_finder(root, finder)
    assert any(place.name == "Honolulu" for place in finder._results)
    assert not finder.table.selection()
    finder = search(towns_screen, "this town is absent from the included catalogue")
    assert not finder._results
    assert "does not mean the place does not exist" in finder.status.get().lower()
    finder = search(towns_screen, "")
    assert finder._results and not finder.table.selection()
    assert panel.pack_info is None


def test_public_marker_clears_without_changing_map_or_database(towns_screen):
    root, panel, app, external = towns_screen
    finder = search(towns_screen, "Tulsa")
    place = select(root, finder, "Tulsa")
    before = app.db.path.read_bytes()
    finder.show_button.invoke()
    wait(root, panel)
    frame = panel.frame
    generation = panel._generation
    panel.clear_town_button.invoke()
    root.update()
    assert panel.frame is frame and panel._images
    assert panel._generation == generation
    assert not panel.canvas.find_withtag("included-town-marker")
    assert panel._included_place is None and app.db.path.read_bytes() == before
    assert panel.show_atlas_place(place)
    wait(root, panel)
    opened(root, panel, external)
    assert panel._included_place is None
    assert not panel.canvas.find_withtag("included-town-marker")
    assert panel.pack_info.path == external.resolve()
    assert app.db.path.read_bytes() == before


def test_late_town_map_open_cannot_replace_external_map(towns_screen, monkeypatch):
    root, panel, _, external = towns_screen
    finder = search(towns_screen, "Tulsa")
    place = select(root, finder, "Tulsa")
    from fieldforge.ui import maps

    original = maps.inspect_pack
    started, release = threading.Event(), threading.Event()

    def delayed(path, **kwargs):
        if path == map_path():
            started.set()
            assert release.wait(3)
        return original(path, **kwargs)

    monkeypatch.setattr(maps, "inspect_pack", delayed)
    try:
        assert panel.show_atlas_place(place)
        assert started.wait(1)
        panel.open_path(external)
    finally:
        release.set()
    wait(root, panel)
    assert panel.pack_info.path == external.resolve()
    assert panel._included_place is None
    assert not panel.canvas.find_withtag("included-town-marker")
    assert panel.view.latitude == panel.view.longitude == 0


def test_cleared_marker_does_not_reappear_after_pending_map_read(towns_screen):
    root, panel, _, _ = towns_screen
    finder = search(towns_screen, "Honolulu")
    place = select(root, finder, "Honolulu")
    assert panel.show_atlas_place(place)
    panel.clear_town_button.invoke()
    wait(root, panel)
    assert panel.frame is not None and panel._images
    assert panel._included_place is None
    assert not panel.canvas.find_withtag("included-town-marker")


def test_included_town_and_region_override_retained_route_without_clearing_it(towns_screen):
    root, panel, app, external = towns_screen
    finder = search(towns_screen, "Tulsa")
    place = select(root, finder, "Tulsa")
    before = app.db.path.read_bytes()
    route = planned_route([[place.longitude - .2, place.latitude],
                           [place.longitude + .2, place.latitude]])
    panel.show_route(route)
    finder.show_button.invoke()
    wait(root, panel)
    assert panel.view.latitude == pytest.approx(place.latitude)
    assert panel.view.longitude == pytest.approx(place.longitude)
    assert panel._route == route and panel._included_place == place
    panel.route_start_button.invoke()
    wait(root, panel)
    assert panel.view.longitude == pytest.approx(place.longitude - .2)
    assert panel._included_place == place
    panel.clear_route()
    assert panel._route is None
    assert panel.canvas.find_withtag("included-town-marker")
    panel.show_route(route)
    wait(root, panel)
    panel.clear_included_place()
    assert panel._route == route and panel._included_place is None
    panel.open_atlas("Hawaii")
    wait(root, panel)
    assert panel.view.latitude == 20.5 and panel.view.longitude == -157.5
    assert panel._route == route
    opened(root, panel, external)
    assert panel.view.longitude == pytest.approx(place.longitude - .2)
    assert app.db.path.read_bytes() == before


@pytest.mark.parametrize("valid", [True, False])
def test_route_selected_during_atlas_open_applies_only_after_validation(
        towns_screen, monkeypatch, valid):
    root, panel, _, _ = towns_screen
    finder = search(towns_screen, "Honolulu")
    place = select(root, finder, "Honolulu")
    from fieldforge.ui import maps

    original = maps.inspect_pack
    started, release = threading.Event(), threading.Event()

    def delayed(path, **kwargs):
        started.set()
        assert release.wait(3)
        return original(path, **kwargs)

    monkeypatch.setattr(maps, "inspect_pack", delayed)
    route = planned_route()
    try:
        assert panel.show_atlas_place(place)
        assert started.wait(1)
        if valid:
            panel.show_route(route)
        else:
            with pytest.raises(ValueError):
                panel.show_route(planned_route([[1800, 0], [0, 0]]))
    finally:
        release.set()
    wait(root, panel)
    assert panel.view.latitude == pytest.approx(10 if valid else place.latitude)
    assert panel.view.longitude == pytest.approx(30 if valid else place.longitude)
    assert panel._included_place == place
    assert panel._route == (route if valid else None)


@pytest.mark.parametrize("close", ["finder", "maps"])
def test_closing_pending_finder_cancels_reader_and_tk_callbacks(towns_screen, monkeypatch, close):
    root, panel, _, _ = towns_screen
    started, cancelled = threading.Event(), threading.Event()

    def blocked_read(*_args, cancel, **_kwargs):
        started.set()
        assert cancel.wait(3)
        cancelled.set()
        raise ValueError("Cancelled test read")

    monkeypatch.setattr("fieldforge_gps.place_jobs.read_catalog", blocked_read)
    panel.open_atlas_search()
    finder = panel._atlas_search
    assert started.wait(1)
    if close == "finder":
        panel.close_atlas_search()
    else:
        panel.destroy()
    assert cancelled.wait(1)
    root.update()
    assert finder._closed and finder._after is None and finder._job is None
    assert panel._atlas_search is None and panel._atlas_window is None


def test_missing_bundled_catalogue_leaves_map_and_private_controls_unchanged(
        towns_screen, monkeypatch, tmp_path):
    root, panel, app, external = towns_screen
    opened(root, panel, external)
    before = app.db.path.read_bytes()
    old_frame = panel.frame
    monkeypatch.setattr(atlas_search, "places_path", lambda: tmp_path / "missing.csv")
    panel.open_atlas_search()
    finder = panel._atlas_search
    settle_finder(root, finder)
    assert finder.catalog is None and "unavailable" in finder.status.get().lower()
    assert str(finder.search_button["state"]) == "disabled"
    assert panel.frame is old_frame and not panel.overlay.get()
    assert app.db.path.read_bytes() == before


def test_town_controls_fit_minimum_windows_and_marker_status_does_not_reload(towns_screen):
    root, panel, _, _ = towns_screen
    root.geometry("1000x700")
    root.update()
    panel.show_route(planned_route())
    finder = search(towns_screen, "Honolulu")
    window = panel._atlas_window
    window.geometry("800x540")
    root.update()
    for widget in (finder.query_entry, finder.search_button, finder.table, finder.show_button):
        assert widget.winfo_rootx() + widget.winfo_width() <= (
            window.winfo_rootx() + window.winfo_width())
        assert widget.winfo_rooty() + widget.winfo_height() <= (
            window.winfo_rooty() + window.winfo_height())
    assert finder.table.winfo_height() >= 100
    select(root, finder, "Honolulu")
    finder.show_button.invoke()
    wait(root, panel)
    for widget in (panel.atlas_search_button, panel.clear_town_button,
                   panel.public_place_label, panel.atlas_button, panel.regional_button,
                   panel.route_start_button, panel.route_details_button,
                   panel.clear_route_button, panel.footer):
        assert widget.winfo_rootx() + widget.winfo_width() <= (
            panel.winfo_rootx() + panel.winfo_width())
        assert widget.winfo_rooty() + widget.winfo_height() <= (
            panel.winfo_rooty() + panel.winfo_height())
    assert panel.canvas.winfo_height() >= 200
    generation = panel._generation
    panel.clear_included_place()
    wait(root, panel)
    assert panel._generation == generation

