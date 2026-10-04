import math
import socket

import pytest

from fieldforge.navigation.map_view import MAX_LATITUDE, Viewport
from fieldforge.navigation.route_view import (
    MAX_PATH_POINTS,
    MAX_ROUTE_POINTS,
    MAX_VISIBLE_SEGMENTS,
    clip_segment,
    prepare_route,
    visible_route,
)


def test_actual_longitude_first_vertices_are_projected_without_shortcuts():
    latitude = math.degrees(math.atan(math.sinh(math.pi / 2)))
    route = prepare_route([[0, 0], [0, latitude], [45, latitude]])
    drawing = visible_route(route, Viewport(0, 0, 1, 512, 512))
    assert len(drawing.paths) == 1
    assert len(drawing.paths[0]) == 3
    for actual, expected in zip(drawing.paths[0], ((256, 256), (256, 128), (320, 128))):
        assert actual == pytest.approx(expected)
    assert drawing.visible_segments == 2 and not drawing.limited
    assert route.start == (0, 0) and route.end == (latitude, 45)
    # This valid longitude cannot be interpreted as latitude.
    east = prepare_route([[100, 45], [110, 40]])
    view = Viewport(45, 100, 5, 512, 300)
    result = visible_route(east, view)
    assert result.paths[0][0] == pytest.approx((256, 150))


@pytest.mark.parametrize("segment,expected", [
    ((-50, 50, 150, 50), (0, 50, 100, 50)),
    ((50, -50, 50, 150), (50, 0, 50, 100)),
    ((-10, -10, 50, 50), (0, 0, 50, 50)),
    ((150, 150, -50, -50), (100, 100, 0, 0)),
    ((0, 0, 0, 100), (0, 0, 0, 100)),
    ((40, 40, 40, 40), (40, 40, 40, 40)),
    ((-20, 50, -10, 50), None),
    ((10, -1, 90, -1), None),
    ((-100, 10, 10, -100), None),
])
def test_segment_clipping_preserves_intersections_and_discards_offscreen(segment, expected):
    clipped = clip_segment(segment, 100, 100)
    assert clipped == (pytest.approx(expected) if expected is not None else None)


def test_date_line_crossing_stays_at_world_edge_and_never_draws_across_greenwich():
    route = prepare_route([[179, 0], [180, 0], [-179, 0]])
    drawing = visible_route(route, Viewport(0, 179, 4, 600, 300))
    assert drawing.visible_segments == 2
    for path in drawing.paths:
        assert max(point[0] for point in path) - min(point[0] for point in path) < 24
        assert all(0 <= x <= 600 and 0 <= y <= 300 for x, y in path)
    assert not visible_route(route, Viewport(0, 0, 4, 600, 300)).paths
    reverse = visible_route(prepare_route([[-179, 0], [179, 0]]), Viewport(0, -179, 4, 600, 300))
    assert reverse.visible_segments == 1
    assert reverse.paths[0][-1][0] < reverse.paths[0][0][0]


def test_zoom_zero_world_copies_are_clipped_at_each_viewport_edge():
    view = Viewport(0, 0, 0, 1000, 256)
    drawing = visible_route(prepare_route([[-20, 0], [20, 0]]), view)
    assert drawing.visible_segments == 5
    assert len(drawing.paths) == 5
    assert drawing.paths[0][0][0] == 0
    assert drawing.paths[-1][-1][0] == 1000
    assert all(0 <= x <= view.width and 0 <= y <= view.height for path in drawing.paths for x, y in path)


def test_exiting_and_reentering_view_does_not_connect_nonadjacent_vertices():
    route = prepare_route([[-10, 0], [100, 0], [100, 70], [10, 70], [10, 0]])
    drawing = visible_route(route, Viewport(0, 0, 2, 200, 200))
    assert len(drawing.paths) == 2
    assert drawing.paths[0][-1] == pytest.approx((200, 100))
    assert drawing.paths[1][0][1] == 0
    for path in drawing.paths:
        for first, second in zip(path, path[1:]):
            assert first[0] == second[0] or first[1] == second[1]


def test_polar_vertices_are_hidden_without_clamping_or_bridging_the_gap():
    route = prepare_route([[-10, 0], [0, 90], [10, 0], [20, 0]])
    assert route.point_count == 4 and route.polar_points == 1
    assert [index for index, _ in route.segments] == [3]
    view = Viewport(0, 0, 2, 512, 400)
    drawing = visible_route(route, view)
    assert drawing.visible_segments == 1
    assert drawing.paths[0][0] == view.locations(0, 10)[0]
    assert drawing.paths[0][1] == view.locations(0, 20)[0]
    all_polar = prepare_route([[0, -90], [5, 90]])
    assert all_polar.start is all_polar.end is None
    assert all_polar.polar_points == 2 and not visible_route(all_polar, view).paths


def test_mercator_edge_is_allowed_without_drawing_into_polar_tile_rows():
    view = Viewport(MAX_LATITUDE, 0, 1, 512, 300)
    route = prepare_route([[-20, MAX_LATITUDE], [20, MAX_LATITUDE]])
    assert route.polar_points == 0
    drawing = visible_route(route, view)
    assert drawing.visible_segments == 1
    assert all(y == pytest.approx(150) for path in drawing.paths for _, y in path)


@pytest.mark.parametrize("geometry", [
    [], [[0, 0]], [[0, 0, 0], [1, 1]], [[0, 0], [181, 0]],
    [[0, 0], [1, 91]], [[0, 0], [True, 1]], [[0, 0], [1, False]],
    [[0, 0], [float("nan"), 0]], [[0, 0], [0, float("inf")]],
    [[0, 0], ["1", 1]], [[0, 0]] * (MAX_ROUTE_POINTS + 1),
])
def test_invalid_or_oversized_geometry_is_rejected(geometry):
    with pytest.raises(ValueError):
        prepare_route(geometry)


def test_display_limit_is_explicit_and_never_replaces_vertices_with_a_shortcut():
    points = [[index * .001, 0] for index in range(10)]
    route = prepare_route(points)
    view = Viewport(0, 0, 8, 512, 256)
    drawing = visible_route(route, view, segment_limit=3)
    assert drawing.visible_segments == 3 and drawing.limited
    assert len(drawing.paths[0]) == 4
    assert drawing.paths[0][-1] == pytest.approx(view.locations(0, .003)[0])
    assert route.point_count == len(points) == 10
    assert not visible_route(prepare_route(points[:4]), view, segment_limit=3).limited


def test_maximum_input_and_canvas_paths_have_bounded_sizes():
    points = [[index * .000001, 0] for index in range(MAX_ROUTE_POINTS)]
    route = prepare_route(points)
    drawing = visible_route(route, Viewport(0, 0, 1, 512, 256))
    assert route.point_count == 50_000
    assert drawing.limited and drawing.visible_segments == MAX_VISIBLE_SEGMENTS
    assert max(len(path) for path in drawing.paths) <= MAX_PATH_POINTS
    assert sum(len(path) - 1 for path in drawing.paths) == MAX_VISIBLE_SEGMENTS


def test_projection_and_clipping_never_use_transport(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Offline route display must not contact any service")
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, fail)
    route = prepare_route([[10, 30], [11, 31]])
    assert visible_route(route, Viewport(30, 10, 5, 500, 400)).paths
