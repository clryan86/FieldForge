from types import SimpleNamespace

import pytest

from fieldforge_gps.mercator import (
    MAX_LAT,
    MercatorView,
    fit_mercator,
    from_unit,
    project_mercator_paths,
    unit_xy,
    visible_cells,
)


@pytest.mark.parametrize(
    "lon,lat,x,y",
    [
        (0, 0, 0.5, 0.5),
        (-180, 0, 0, 0.5),
        (180, 0, 1, 0.5),
        (0, MAX_LAT, 0.5, 0),
        (0, -MAX_LAT, 0.5, 1),
    ],
)
def test_independent_projection_anchors(lon, lat, x, y):
    assert unit_xy(lon, lat) == pytest.approx((x, y))


@pytest.mark.parametrize("lon,lat", [(-179, -80), (-90, 45), (0, 0), (70, 70), (179, 80)])
def test_roundtrip(lon, lat):
    assert from_unit(*unit_xy(lon, lat)) == pytest.approx((lon, lat))


@pytest.mark.parametrize(
    "lon,lat",
    [
        (0, 90),
        (0, -90),
        (181, 0),
        (-181, 0),
        (0, float("nan")),
        (float("inf"), 0),
        (True, 0),
        (0, "1"),
    ],
)
def test_bad_coordinates_rejected(lon, lat):
    with pytest.raises(ValueError):
        unit_xy(lon, lat)


@pytest.mark.parametrize("args", [(180, 0, 1), (0, 0, 23), (0, 0, -1), (0, 0, True), (0, 90, 0)])
def test_invalid_views(args):
    with pytest.raises(ValueError):
        MercatorView(*args)


def test_tile_grid_origin_and_no_offscreen_boundary_cells():
    cells = visible_cells(MercatorView(0, 0, 0), 256, 256)
    assert len(cells) == 1 and cells[0].key == (0, 0, 0)
    assert cells[0].screen_x == pytest.approx(0) and cells[0].screen_y == pytest.approx(0)


def test_horizontal_repetition_does_not_repeat_poles():
    cells = visible_cells(MercatorView(0, 0, 0), 768, 768)
    assert len(cells) == 9
    assert sum(c.key is None for c in cells) == 6
    assert {c.key for c in cells if c.key} == {(0, 0, 0)}


@pytest.mark.parametrize(
    "width,height", [(0, 100), (3000, 100), (100, 1700), (True, 100), (10.5, 100)]
)
def test_viewport_limits(width, height):
    with pytest.raises(ValueError):
        visible_cells(MercatorView(), width, height)


def test_max_viewport_bounded():
    assert len(visible_cells(MercatorView(17, 33, 3), 2560, 1600)) <= 96


def test_pan_direction_and_polar_limit():
    v = MercatorView(0, 0, 2)
    assert v.pan(256, 0, 512, 512).longitude == pytest.approx(-90)
    assert v.pan(0, 256, 512, 512).latitude > 0
    assert v.pan(0, 10**6, 512, 512).latitude == pytest.approx(MAX_LAT)
    assert v.position(0, 90, 512, 512) is None


def test_position_registration_at_equator():
    v = MercatorView(0, 0, 2)
    assert v.position(-90, 0, 1024, 512) == pytest.approx((256, 256))
    assert v.position(90, 0, 1024, 512) == pytest.approx((768, 256))


def test_date_line_short_path_not_cross_world_chord():
    v = MercatorView(0, 0, 2)
    paths = project_mercator_paths([(179, 0), (-179, 0)], v, 1024, 512)
    assert len(paths) == 2
    assert all(abs(p[-1][0] - p[0][0]) < 5 for p in paths)


def test_date_line_center_shows_connected_path():
    v = MercatorView(-180, 0, 3)
    paths = project_mercator_paths([(179, 0), (-179, 0)], v, 600, 400)
    assert len(paths) == 1
    assert paths[0][0][0] < 300 < paths[0][-1][0]


def test_polar_points_break_line_instead_of_bridging():
    assert not project_mercator_paths([(0, 0), (0, 90), (10, 0)], MercatorView(0, 0, 2), 600, 400)


def test_clip_stays_inside_viewport():
    paths = project_mercator_paths([(-100, 40), (100, -40)], MercatorView(), 300, 200)
    assert paths
    assert all(0 <= x <= 300 and 0 <= y <= 200 for p in paths for x, y in p)


def test_fit_uses_short_longitude_arc_and_observed_zoom():
    points = [
        SimpleNamespace(longitude=179, latitude=5),
        SimpleNamespace(longitude=-179, latitude=6),
    ]
    v = fit_mercator(points, 800, 500, (0, 2, 4, 6))
    assert abs(v.longitude) > 170 and v.level in (0, 2, 4, 6)
    assert all(32 <= v.position(p.longitude, p.latitude, 800, 500)[0] <= 768 for p in points)


def test_polar_fit_does_not_invent_center():
    with pytest.raises(ValueError, match="No selected"):
        fit_mercator([SimpleNamespace(longitude=0, latitude=90)], 800, 500, (0, 2))


def test_contiguous_dense_path_is_batched_not_thousands_of_canvas_lines():
    points = [(i * 0.001, 0) for i in range(8000)]
    paths = project_mercator_paths(points, MercatorView(4, 0, 3), 800, 500)
    assert len(paths) == 1 and len(paths[0]) == 8000
