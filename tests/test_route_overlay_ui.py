"""Saved planned routes render on real local MBTiles with all transport disabled."""

import copy
import json
import socket
import urllib.request
from types import SimpleNamespace

import pytest
from map_fixture import make_map
from test_maps_ui import opened, wait
from test_maps_ui import screen as screen


def planned_route(geometry=None):
    geometry = geometry or [[30, 10], [31, 11], [32, 11]]
    return {
        "id": "fictional-route",
        "title": "Fictional saved plan",
        "mode": "driving",
        "distance_m": 1200,
        "duration_s": 240,
        "geometry": geometry,
        "steps": [{"instruction": "Fictional test instruction", "distance_m": 1200,
                   "duration_s": 240, "latitude": geometry[0][1], "longitude": geometry[0][0]}],
        "start": {"latitude": geometry[0][1], "longitude": geometry[0][0]},
        "end": {"latitude": geometry[-1][1], "longitude": geometry[-1][0]},
        "source": "Original fictional route fixture",
        "attribution": "Original FieldForge test geometry. Not for navigation.",
        "license": "CC0-1.0 test fixture",
        "created_at": "2026-10-04T00:00:00Z",
    }


@pytest.fixture
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("No online transport is allowed for a saved route overlay")
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, denied)
    monkeypatch.setattr(urllib.request, "urlopen", denied)


def line_coordinates(panel):
    return [panel.canvas.coords(item) for item in panel.canvas.find_withtag("route-line")]


def test_saved_route_before_map_is_retained_and_opens_offline_without_writes(screen, offline, tmp_path):
    root, panel, app, path = screen
    route = planned_route()
    # Requested endpoints may differ from the provider's actual snapped path.
    route["start"] = {"latitude": 9, "longitude": 29}
    saved_file = tmp_path / "saved-plan.json"
    saved_file.write_text(json.dumps(route), encoding="utf-8")
    saved_bytes = saved_file.read_bytes()
    before_map, before_db = path.read_bytes(), app.db.path.read_bytes()
    panel.show_route(route)
    assert panel.pack_info is None and panel.route == route
    assert "Open a local" in panel.status.get() and "open a local map" in panel.route_status.get()
    assert str(panel.route_details_button["state"]) == "normal"
    assert str(panel.clear_route_button["state"]) == "normal"
    assert not panel.canvas.find_withtag("planned-route")
    route["geometry"][0][0] = -100
    route["steps"][0]["instruction"] = "Caller edited this later"
    assert panel.route["geometry"][0] == [30, 10]
    assert panel.route["steps"][0]["instruction"] == "Fictional test instruction"
    opened(root, panel, path)
    assert (panel.view.latitude, panel.view.longitude) == (10, 30)
    assert panel.canvas.find_withtag("route-line")
    assert panel.canvas.find_withtag("route-start") and panel.canvas.find_withtag("route-end")
    assert not panel.overlay.get() and not panel.canvas.find_withtag("private-marker")
    assert "Planned route" in panel.route_status.get()
    assert path.read_bytes() == before_map and app.db.path.read_bytes() == before_db
    assert saved_file.read_bytes() == saved_bytes


def test_pan_and_zoom_redraw_actual_vertices_and_do_not_create_location_history(screen, offline):
    root, panel, app, path = screen
    opened(root, panel, path)
    panel.show_route(planned_route())
    wait(root, panel)
    before = copy.deepcopy(panel.route)
    coordinates = line_coordinates(panel)
    assert coordinates and coordinates[0][:2] == pytest.approx((panel.view.width / 2, panel.view.height / 2))
    panel.minus.invoke()
    wait(root, panel)
    assert panel.view.zoom == 1
    assert line_coordinates(panel) != coordinates
    panel.key(SimpleNamespace(keysym="Right"))
    wait(root, panel)
    panel.route_start_button.invoke()
    wait(root, panel)
    assert (panel.view.latitude, panel.view.longitude) == (10, 30)
    assert panel.route == before and not app.waypoints()
    panel.motion(SimpleNamespace(x=panel.view.width / 2, y=panel.view.height / 2))
    assert "NOT GPS" in panel.pointer.get()
    for values in line_coordinates(panel):
        assert all(0 <= x <= panel.view.width for x in values[0::2])
        assert all(0 <= y <= panel.view.height for y in values[1::2])


def test_date_line_route_has_short_wrapped_segments_and_offscreen_status(screen, offline):
    root, panel, _, path = screen
    root.geometry("1000x700")
    root.update()
    opened(root, panel, path)
    panel.show_route(planned_route([[179, 0], [180, 0], [-179, 0]]))
    wait(root, panel)
    assert panel.view.longitude == 179
    assert line_coordinates(panel)
    assert all(max(values[0::2]) - min(values[0::2]) < 10 for values in line_coordinates(panel))
    panel._set_view(0, 0, 2)
    wait(root, panel)
    assert not panel.canvas.find_withtag("route-line")
    assert "outside this view" in panel.route_status.get()
    panel.route_start_button.invoke()
    wait(root, panel)
    assert panel.canvas.find_withtag("route-line")


def test_map_close_replacement_missing_tiles_and_failure_preserve_route(screen, offline, tmp_path):
    root, panel, _, path = screen
    panel.show_route(planned_route([[-1, 0], [0, 1], [1, 0]]))
    route = copy.deepcopy(panel.route)
    opened(root, panel, path)
    panel.close_button.invoke()
    assert panel.route == route and panel.frame is None
    assert "retained" in panel.status.get() and "open a local map" in panel.route_status.get()
    assert not panel.canvas.find_withtag("planned-route")
    hole = make_map(tmp_path / "missing-tiles.mbtiles", missing=((2, 1, 1), (2, 2, 1), (2, 1, 2), (2, 2, 2)))
    opened(root, panel, hole)
    assert panel.route == route and panel.canvas.find_withtag("route-line")
    assert "not installed" in panel.status.get()
    panel.open_path(tmp_path / "map-does-not-exist.mbtiles")
    wait(root, panel)
    assert panel.route == route and panel.frame is None
    assert "failed" in panel.status.get() and "open a local map" in panel.route_status.get()
    assert str(panel.route_details_button["state"]) == "normal"
    opened(root, panel, path)
    assert panel.route == route and panel.canvas.find_withtag("route-line")


def test_clear_removes_only_the_overlay_and_invalid_replacement_preserves_good_route(screen, offline):
    root, panel, _, path = screen
    opened(root, panel, path)
    panel.show_route(planned_route())
    wait(root, panel)
    before, previous_frame = copy.deepcopy(panel.route), panel.frame
    bad = planned_route([[1800, 0], [0, 0]])
    with pytest.raises(ValueError):
        panel.show_route(bad)
    assert panel.route == before and panel.frame is previous_frame
    assert panel.canvas.find_withtag("route-line")
    panel.clear_route_button.invoke()
    assert panel.route is None and panel.frame is previous_frame
    assert panel._images and not panel.canvas.find_withtag("planned-route")
    assert str(panel.clear_route_button["state"]) == "disabled"
    assert "No saved route file was deleted" in panel.status.get()
    panel.close_map()
    opened(root, panel, path)
    assert panel.route is None and not panel.canvas.find_withtag("planned-route")


def test_polar_route_start_is_never_replaced_or_joined_across_gap(screen, offline):
    root, panel, _, path = screen
    opened(root, panel, path)
    view = panel.view
    panel.show_route(planned_route([[0, 89], [0, 0], [10, 0], [20, 89], [30, 0]]))
    root.update()
    assert panel.view == view
    assert not panel.canvas.find_withtag("route-start")
    assert panel.canvas.find_withtag("route-end")
    assert str(panel.route_start_button["state"]) == "disabled"
    assert "2 polar point(s) hidden" in panel.route_status.get()
    assert "start is outside" in panel.status.get()
    assert panel._route_drawing.visible_segments == 1
    assert panel.route["geometry"][0] == [0, 89]


def test_route_details_preserve_full_attribution_and_original_plan_timestamp_as_inert_text(screen, offline):
    root, panel, _, _ = screen
    route = planned_route()
    attribution = '<script>inert()</script> https://example.invalid/route\n' * 40
    route["attribution"] = attribution.strip()
    panel.show_route(route)
    window = panel.route_details()
    root.update()
    def texts(widget):
        if widget.winfo_class() == "Text":
            yield widget
        for child in widget.winfo_children():
            yield from texts(child)
    content = next(texts(window)).get("1.0", "end")
    assert attribution.strip() in content and route["source"] in content and route["license"] in content
    assert "Provider plan timestamp: 2026-10-04T00:00:00Z" in content
    assert "not a recorded journey" in content and "No live guidance" in content
    assert "Geometry start: latitude 10.0000000, longitude 30.0000000" in content
    window.destroy()


def test_route_controls_fit_minimum_window_without_canvas_resize_loop(screen, offline):
    root, panel, _, path = screen
    root.geometry("1000x700")
    root.update()
    opened(root, panel, path)
    panel.show_route(planned_route())
    wait(root, panel)
    assert panel.canvas.winfo_height() >= 200
    for widget in (panel.route_start_button, panel.route_details_button, panel.clear_route_button, panel.footer):
        assert widget.winfo_rootx() + widget.winfo_width() <= panel.winfo_rootx() + panel.winfo_width()
        assert widget.winfo_rooty() + widget.winfo_height() <= panel.winfo_rooty() + panel.winfo_height()
    generation = panel._generation
    panel.motion(SimpleNamespace(x=panel.view.width / 2, y=panel.view.height / 2))
    wait(root, panel)
    assert panel._generation == generation


def test_display_cap_is_visible_while_complete_saved_geometry_is_retained(screen, offline):
    root, panel, _, path = screen
    opened(root, panel, path)
    geometry = [[index * .000001, 0] for index in range(12_002)]
    panel.show_route(planned_route(geometry))
    wait(root, panel)
    assert panel._route_drawing.limited
    assert "display limit reached" in panel.route_status.get()
    assert len(panel.route["geometry"]) == 12_002
