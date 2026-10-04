"""Cross-feature contracts for the combined GPS / places / GPX workspace."""

import pytest

from fieldforge_gps.places import Place

from .test_live_map_ui import fresh, has_fix, local
from .test_live_map_ui import ui as ui
from .test_nmea import rmc
from .test_places_ui import settle


def open_places(ui):
    root, _, frame = ui
    panel = frame.open_finder()
    panel.permission.set(True)
    panel.wgs84.set(True)
    panel.example()
    settle(root, frame)
    return panel


def select_springs(ui, panel):
    root, _, frame = ui
    panel.query.set("springs north")
    panel.search()
    settle(root, frame)
    panel.table.selection_set("0")
    panel._selected()
    assert panel.show_selected()
    settle(root, frame)


def test_places_work_without_connecting_receiver(ui):
    _, gps, frame = ui
    panel = open_places(ui)
    select_springs(ui, panel)
    assert frame._place_marker[0].name == "Fictional Springs"
    assert frame.canvas.find_withtag("place-marker")
    assert gps.session is None
    assert not frame.show_live.get() and not frame.follow_live.get()


def test_open_and_search_do_not_interrupt_follow(ui):
    root, _, frame = ui
    _, session = fresh(ui)
    frame.follow_live.set(True)
    before = frame.view
    panel = open_places(ui)
    panel.query.set("springs")
    panel.search()
    settle(root, frame)
    assert frame.follow_live.get() and frame.view == before
    assert session.trip_summary().state == "idle"


@pytest.mark.parametrize("origin", ["FILE PLACE", "MANUAL COORDINATE"])
def test_center_reference_pauses_follow_without_turning_off_live(ui, origin):
    root, _, frame = ui
    _, session = fresh(ui)
    frame.follow_live.set(True)
    frame.show_place(Place(0, "Fictional nearby reference", 10.1, 20.1), origin)
    settle(root, frame)
    assert not frame.follow_live.get() and frame.show_live.get()
    assert frame.view.latitude == 10.1 and frame.view.longitude == pytest.approx(20.1)
    assert has_fix(frame) and frame.canvas.find_withtag("place-marker")
    assert "Follow paused" in frame.live_notice.get()
    before = frame.view
    session._feed(rmc(time="120001", lat="1100.0"))
    frame.refresh_live()
    assert frame.view == before and not frame.follow_live.get()
    assert session.trip_summary().state == "idle"


@pytest.mark.parametrize(
    "place,origin",
    [
        (Place(0, "", 10, 20), "FILE PLACE"),
        (Place(0, "Bad latitude", 91, 20), "FILE PLACE"),
        (Place(0, "Bad longitude", 10, 181), "MANUAL COORDINATE"),
        (Place(0, "Wrong origin", 10, 20), "LIVE"),
    ],
)
def test_rejected_reference_keeps_follow_and_previous_marker(ui, place, origin):
    _, _, frame = ui
    fresh(ui)
    frame.show_place(Place(0, "Original reference", 10, 20), "MANUAL COORDINATE")
    frame.follow_live.set(True)
    before, marker = frame.view, frame._place_marker
    with pytest.raises(ValueError):
        frame.show_place(place, origin)
    assert frame.follow_live.get() and frame.view == before
    assert frame._place_marker is marker


def test_rejected_polar_reference_keeps_follow_on_local_map(ui):
    _, _, frame = ui
    local(ui)
    fresh(ui)
    frame.follow_live.set(True)
    before = frame.view
    with pytest.raises(ValueError, match="not clamped"):
        frame.show_place(Place(0, "Fictional pole", 89, 0), "FILE PLACE")
    assert frame.view == before and frame.follow_live.get()


def test_three_layers_coexist_and_clear_independently(ui):
    root, gps, frame = ui
    frame.datum.set(True)
    frame.consent.set(True)
    frame.example()
    settle(root, frame)
    doc = frame.document
    fresh(ui)
    frame.show_place(Place(0, "Fictional reference", 10.1, 20.1), "FILE PLACE")
    settle(root, frame)
    marker = frame._place_marker
    assert doc is not None and has_fix(frame)
    assert frame.canvas.find_withtag("place-marker")
    gps.datum.set(False)
    assert not has_fix(frame) and frame._place_marker is marker and frame.document is doc
    frame.clear_place_marker()
    assert not frame.canvas.find_withtag("place-marker")
    assert not frame.canvas.find_withtag("place-marker-label")
    assert frame.document is doc


def test_place_revocation_leaves_live_fix_and_map(ui):
    root, _, frame = ui
    local(ui)
    panel = open_places(ui)
    fresh(ui, lat="3200.000", lon="00000.000")
    select_springs(ui, panel)
    pack = frame.map_pack
    assert has_fix(frame)
    panel.permission.set(False)
    assert frame._place_marker is None and panel.catalog is None
    assert not frame.canvas.find_withtag("place-marker")
    assert has_fix(frame) and frame.map_pack is pack and frame.show_live.get()
    settle(root, frame)


def test_reference_move_clears_old_tiles_synchronously(ui):
    root, _, frame = ui
    local(ui)
    fresh(ui, lat="3200.000", lon="00000.000")
    frame.center_live()
    settle(root, frame)
    assert frame.canvas.find_withtag("map-tile")
    frame.show_place(Place(0, "Fictional new view", 32.4, 0.4), "FILE PLACE")
    assert not frame.canvas.find_withtag("map-tile")
    assert not frame.canvas.find_withtag("place-marker")
    settle(root, frame)
    assert frame.canvas.find_withtag("place-marker")


def test_manual_marker_survives_closing_finder(ui):
    root, _, frame = ui
    panel = open_places(ui)
    fresh(ui)
    panel.latitude.set("10.1")
    panel.longitude.set("20.1")
    panel.show_manual()
    settle(root, frame)
    worker = panel.worker
    frame.close_finder()
    worker._thread.join(2)
    assert not worker._thread.is_alive()
    assert frame._place_marker[1] == "MANUAL COORDINATE" and has_fix(frame)


@pytest.mark.parametrize("method", ["close", "destroy_window", "destroy_receiver"])
def test_combined_close_stops_finder_and_map_workers(ui, method):
    root, gps, frame = ui
    panel = open_places(ui)
    _, session = fresh(ui)
    workers = [frame._map_reader, panel.worker]
    if method == "close":
        frame.close()
    elif method == "destroy_window":
        gps.live_map_window.destroy()
    else:
        gps.destroy()
    for worker in workers:
        worker._thread.join(2)
        assert not worker._thread.is_alive()
    assert frame._closed and frame._live_after is None and frame.finder is None
    if method != "destroy_receiver":
        assert session.snapshot().running


def test_reopen_has_no_retained_places_or_live_consent(ui):
    root, gps, frame = ui
    panel = open_places(ui)
    worker = panel.worker
    fresh(ui)
    select_springs(ui, panel)
    gps.live_map_window.destroy()
    worker._thread.join(2)
    again = gps.open_live_map()
    assert again is not frame and again.finder is None and again._place_marker is None
    assert not again.show_live.get() and not again.follow_live.get()
    reader = again._map_reader
    again.close()
    reader._thread.join(2)
    assert not reader._thread.is_alive()
