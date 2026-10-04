import time
from pathlib import Path

import pytest

from fieldforge_gps.places import Place
from fieldforge_gps.places_map_ui import PlacesMapReviewFrame
from fieldforge_gps.review_map import View


@pytest.fixture
def ui():
    import tkinter as tk

    root = tk.Tk()
    root.geometry("1240x1040")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    frame = PlacesMapReviewFrame(root)
    root.update()
    workers = [frame._map_reader]
    yield root, frame, workers
    if frame.finder is not None:
        workers.append(frame.finder.worker)
    frame.close()
    root.destroy()
    for worker in workers:
        worker._thread.join(2)
        assert not worker._thread.is_alive()
    assert not errors


def settle(root, frame, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
        finder = frame.finder
        if (
            not frame._busy
            and not frame._map_loading
            and not frame._map_task
            and frame._draw_after is None
            and (finder is None or finder._job is None)
        ):
            root.update()
            return
    raise AssertionError("Application did not settle")


def finder(ui, load=True):
    root, frame, workers = ui
    panel = frame.open_finder()
    workers.append(panel.worker)
    root.update()
    if load:
        panel.permission.set(True)
        panel.wgs84.set(True)
        panel.demo_button.invoke()
        settle(root, frame)
        assert len(panel.catalog.places) == 6
    return root, frame, panel


def search(ui, query):
    root, frame, panel = finder(ui)
    panel.query.set(query)
    panel.search_button.invoke()
    settle(root, frame)
    return root, frame, panel


def select(panel, index=0):
    panel.table.selection_set(str(index))
    panel._selected()


def test_startup_has_no_place_index_or_marker(ui):
    root, frame, panel = finder(ui, False)
    assert not panel.permission.get() and not panel.wgs84.get()
    assert panel.catalog is None and frame._place_marker is None
    assert str(panel.open_button["state"]) == "disabled"
    assert not frame.document and not frame.map_pack


def test_permission_checked_before_source_read(ui, tmp_path):
    _, _, panel = finder(ui, False)
    assert panel.start_read(tmp_path / "missing.csv") is False
    assert "Nothing was read" in panel.status.get()


def test_duplicate_matches_require_explicit_selection(ui):
    root, frame, panel = search(ui, "fictional springs")
    assert len(panel.table.get_children()) == 2
    assert not panel.table.selection() and str(panel.show_button["state"]) == "disabled"
    assert panel.show_selected() is False and frame._place_marker is None
    select(panel, 1)
    panel.show_button.invoke()
    settle(root, frame)
    place, origin = frame._place_marker
    assert place.region == "South District" and origin == "FILE PLACE"
    assert frame.canvas.find_withtag("place-marker")
    assert (frame.view.latitude, frame.view.longitude) == pytest.approx((32.4, 0.4), abs=1e-10)


def test_accent_alias_and_context_search_actual_controls(ui):
    root, frame, panel = search(ui, "cafe north")
    assert len(panel._results) == 1 and panel._results[0].name == "Fictional Café Camp"
    select(panel)
    assert panel.show_selected()
    settle(root, frame)
    assert "FILE PLACE" in frame.place_notice.get() and "Fictional Café" in panel.detail.get()


def test_query_edit_invalidates_selectable_results_immediately(ui):
    root, frame, panel = search(ui, "springs")
    select(panel)
    panel.query.set("cafe")
    assert not panel._results and not panel.table.selection()
    assert str(panel.show_button["state"]) == "disabled" and not panel.show_selected()
    panel.search()
    settle(root, frame)
    assert len(panel._results) == 1 and not panel.table.selection()


def test_invalid_query_keeps_catalog_and_publishes_no_results(ui):
    root, frame, panel = search(ui, "x" * 161)
    assert panel.catalog is not None and not panel._results
    assert "160 characters" in panel.status.get()


def test_blank_query_is_not_match_all(ui):
    root, frame, panel = search(ui, "")
    assert not panel._results and "Enter a name" in panel.status.get()


@pytest.mark.parametrize("attribute", ["permission", "wgs84"])
def test_revoking_permission_clears_file_marker_not_map_or_gpx(ui, attribute):
    root, frame, panel = search(ui, "springs north")
    frame.datum.set(True)
    frame.consent.set(True)
    frame.example_button.invoke()
    frame.map_trust.set(True)
    frame.demo_map_button.invoke()
    settle(root, frame)
    select(panel)
    panel.show_selected()
    settle(root, frame)
    doc, pack = frame.document, frame.map_pack
    getattr(panel, attribute).set(False)
    settle(root, frame)
    assert panel.catalog is None and not panel._results and panel.query.get() == ""
    assert frame._place_marker is None and frame.document is doc and frame.map_pack is pack


def test_manual_coordinates_work_without_file_consent(ui):
    root, frame, panel = finder(ui, False)
    panel.latitude.set("35.25")
    panel.longitude.set("-99.75")
    panel.manual_button.invoke()
    settle(root, frame)
    assert frame._place_marker[1] == "MANUAL COORDINATE" and panel.catalog is None
    assert (frame.view.latitude, frame.view.longitude) == (35.25, -99.75)
    assert "not a GPS fix" in panel.manual_status.get()


@pytest.mark.parametrize(
    "latitude,longitude", [("bad", "3"), ("91", "0"), ("0", "181"), ("NaN", "3"), ("3", "")]
)
def test_bad_manual_coordinate_does_not_move_map(ui, latitude, longitude):
    root, frame, panel = finder(ui, False)
    before = frame.view
    panel.latitude.set(latitude)
    panel.longitude.set(longitude)
    assert panel.show_manual() is False
    assert frame.view == before and frame._place_marker is None


def test_manual_marker_is_independent_of_catalog_clear(ui):
    root, frame, panel = finder(ui)
    panel.latitude.set("1")
    panel.longitude.set("2")
    assert panel.show_manual()
    marker = frame._place_marker
    panel.clear_button.invoke()
    settle(root, frame)
    assert frame._place_marker is marker and panel.catalog is None
    frame.clear_place_button.invoke()
    assert frame._place_marker is None


def test_manual_dateline_wrap_preserves_original_coordinate(ui):
    root, frame, panel = finder(ui, False)
    panel.latitude.set("0")
    panel.longitude.set("180")
    panel.show_manual()
    settle(root, frame)
    assert frame.view.longitude == -180 and frame._place_marker[0].longitude == 180
    assert frame.canvas.find_withtag("place-marker")


def test_polar_place_rejected_without_clamping_on_local_map(ui):
    root, frame, panel = search(ui, "polar")
    frame.map_trust.set(True)
    frame.demo_map_button.invoke()
    settle(root, frame)
    before = frame.view
    select(panel)
    assert not panel.show_selected()
    assert frame.view == before and frame._place_marker is None
    assert "not clamped" in panel.status.get()
    frame.close_map_button.invoke()
    settle(root, frame)
    assert panel.show_selected()
    settle(root, frame)
    assert isinstance(frame.view, View) and frame.view.latitude == 89


def test_place_marker_distinct_from_historical_gpx_point(ui):
    root, frame, panel = search(ui, "springs north")
    frame.datum.set(True)
    frame.consent.set(True)
    frame.example_button.invoke()
    settle(root, frame)
    doc = frame.document
    select(panel)
    assert panel.show_selected()
    settle(root, frame)
    assert frame.document is doc and frame._place_marker[1] == "FILE PLACE"
    assert frame.canvas.find_withtag("place-marker")
    assert frame.canvas.type(frame.canvas.find_withtag("place-marker")[0]) == "polygon"


def test_marker_kept_after_gpx_clear_and_map_close(ui):
    root, frame, panel = search(ui, "springs north")
    frame.map_trust.set(True)
    frame.demo_map_button.invoke()
    settle(root, frame)
    select(panel)
    panel.show_selected()
    settle(root, frame)
    marker = frame._place_marker
    frame.clear_button.invoke()
    assert frame._place_marker is marker
    frame.close_map_button.invoke()
    settle(root, frame)
    assert frame._place_marker is marker and panel.catalog is not None


def test_map_marker_waits_for_new_map_frame(ui):
    # South differs from pack start; North is now intentionally at pack start.
    root, frame, panel = search(ui, "springs south")
    frame.map_trust.set(True)
    frame.demo_map_button.invoke()
    settle(root, frame)
    select(panel)
    assert panel.show_selected()
    frame.draw()
    assert not frame.canvas.find_withtag("place-marker")
    settle(root, frame)
    assert frame.canvas.find_withtag("place-marker")
    frame.zoom(2)
    frame.draw()
    assert not frame.canvas.find_withtag("place-marker")
    settle(root, frame)
    assert frame.canvas.find_withtag("place-marker")


def test_dialog_cancel_preserves_catalog_marker(ui, monkeypatch):
    root, frame, panel = search(ui, "springs north")
    select(panel)
    panel.show_selected()
    catalog, marker = panel.catalog, frame._place_marker
    monkeypatch.setattr(
        "fieldforge_gps.place_search_ui.filedialog.askopenfilename", lambda **kwargs: ""
    )
    panel.open_button.invoke()
    assert panel.catalog is catalog and frame._place_marker is marker


def test_dialog_permission_rechecked(ui, monkeypatch, tmp_path):
    root, frame, panel = finder(ui)

    def dialog(**kwargs):
        panel.permission.set(False)
        return str(tmp_path / "absent.csv")

    monkeypatch.setattr("fieldforge_gps.place_search_ui.filedialog.askopenfilename", dialog)
    panel.open_button.invoke()
    settle(root, frame)
    assert panel.catalog is None and panel._job is None
    assert "Nothing was read" in panel.status.get()


def test_failed_new_catalog_clears_old_places_and_marker(ui, tmp_path):
    root, frame, panel = search(ui, "springs north")
    select(panel)
    panel.show_selected()
    panel.start_read(tmp_path / "missing.csv")
    settle(root, frame)
    assert panel.catalog is None and frame._place_marker is None and not panel._results
    assert "failed" in panel.status.get()


def test_clear_while_loading_rejects_late_result(ui):
    root, frame, panel = finder(ui)
    panel.example()
    panel.clear()
    settle(root, frame)
    assert panel.catalog is None and panel._job is None and not panel._results


def test_finder_reuses_open_window_then_closes_worker(ui):
    root, frame, panel = finder(ui)
    assert frame.open_finder() is panel
    worker = panel.worker
    frame.close_finder()
    root.update()
    worker._thread.join(2)
    assert frame.finder is None and not worker._thread.is_alive()
    assert frame.open_finder().catalog is None
    ui[2].append(frame.finder.worker)


def test_close_finder_discards_file_marker_not_manual(ui):
    root, frame, panel = search(ui, "springs north")
    select(panel)
    panel.show_selected()
    frame.close_finder()
    settle(root, frame)
    assert frame._place_marker is None


def test_bad_show_place_api_rejected(ui):
    _, frame, _ = ui
    with pytest.raises(ValueError):
        frame.show_place(None, "FILE PLACE")
    with pytest.raises(ValueError):
        frame.show_place(Place(1, "X", 0, 0), "LIVE GPS")
    with pytest.raises(ValueError):
        frame.show_place(Place(1, "X", 100, 0), "FILE PLACE")


def test_source_and_map_state_stable_without_actions(ui):
    root, frame, panel = search(ui, "springs north")
    frame.map_trust.set(True)
    frame.demo_map_button.invoke()
    settle(root, frame)
    select(panel)
    panel.show_selected()
    settle(root, frame)
    tokens = (panel.worker.token, frame._map_reader.token)
    deadline = time.monotonic() + 0.25
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)
    assert tokens == (panel.worker.token, frame._map_reader.token)


def test_geojson_fixture_import_uses_real_controls(ui):
    root, frame, panel = finder(ui, False)
    panel.permission.set(True)
    panel.wgs84.set(True)
    from fieldforge_gps import places

    path = Path(places.__file__).parent / "data/FICTIONAL-PLACES.geojson"
    panel.start_read(path)
    settle(root, frame)
    assert panel.catalog.format == "geojson" and len(panel.catalog.places) == 6
    panel.query.set("cafe")
    panel.search_button.invoke()
    settle(root, frame)
    assert len(panel._results) == 1
    select(panel)
    assert panel.show_selected()
    settle(root, frame)
    assert (frame._place_marker[0].latitude, frame._place_marker[0].longitude) == (32.1, 0.2)


def test_direct_window_destruction_releases_place_worker(ui):
    root, frame, panel = finder(ui)
    worker = panel.worker
    frame._finder_window.destroy()
    root.update()
    worker._thread.join(2)
    assert not worker._thread.is_alive()
    assert frame.finder is None and frame._finder_window is None
    assert frame.open_finder().catalog is None
    ui[2].append(frame.finder.worker)


def test_same_view_place_uses_current_frame_without_reloading(ui):
    root, frame, panel = search(ui, "springs north")
    frame.map_trust.set(True)
    frame.demo_map_button.invoke()
    settle(root, frame)
    previous = frame.view
    token = frame._map_reader.token
    select(panel)
    assert panel.show_selected()
    frame.draw()
    assert frame.view == previous
    assert frame.canvas.find_withtag("place-marker")
    settle(root, frame)
    assert frame._map_reader.token == token


def test_root_destruction_stops_both_workers_without_widget_errors():
    import tkinter as tk

    root = tk.Tk()
    root.geometry("1240x1040")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    frame = PlacesMapReviewFrame(root)
    panel = frame.open_finder()
    root.update()
    panel.permission.set(True)
    panel.wgs84.set(True)
    panel.example()
    workers = [panel.worker, frame._map_reader]
    root.destroy()
    for worker in workers:
        worker._thread.join(2)
        assert not worker._thread.is_alive()
    assert not errors


def test_destroy_finder_during_load_discards_pending_result(ui):
    root, frame, panel = finder(ui, False)
    panel.permission.set(True)
    panel.wgs84.set(True)
    panel.example()
    worker = panel.worker
    frame._finder_window.destroy()
    root.update()
    worker._thread.join(2)
    assert not worker._thread.is_alive() and worker.poll() is None
    assert frame.finder is None and frame._place_marker is None
