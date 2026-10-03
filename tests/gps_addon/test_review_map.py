import math
import random

import pytest

from fieldforge_gps.gpx_review import ReviewPoint as P
from fieldforge_gps.review_map import (
    DISPLAY_POINTS,
    MIN_SPAN,
    View,
    clip_line,
    connected_length_m,
    fit_points,
    load_overview,
    project_paths,
    sample_segments,
    wrap,
)


def test_overview_integrity_and_declared_geometry_counts():
    rings = load_overview()
    assert len(rings) == 128
    assert sum(map(len, rings)) == 5165
    assert all(-180 <= lon <= 180 and -90 <= lat <= 90 for r in rings for lon, lat in r)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(span=0),
        dict(span=361),
        dict(latitude=91),
        dict(longitude=180),
        dict(latitude=float("nan")),
        dict(span=True),
    ],
)
def test_invalid_views_rejected(kwargs):
    with pytest.raises(ValueError):
        View(**kwargs)


@pytest.mark.parametrize("width,height", [(1000, 500), (500, 1000), (1200, 400)])
def test_world_view_preserves_two_to_one_geographic_scale(width, height):
    view = View()
    scale = view.scale(width, height)
    assert scale * 360 <= width + 1e-9 and scale * 180 <= height + 1e-9
    assert view.position(0, 0, width, height) == (width / 2, height / 2)


def test_fit_date_line_points_together_not_at_greenwich():
    view = fit_points((P(10, 179), P(11, -179)), 1000, 500)
    assert abs(view.longitude) > 170 and view.span < 10
    for p in (P(10, 179), P(11, -179)):
        x, y = view.position(p.longitude, p.latitude, 1000, 500)
        assert 0 <= x <= 1000 and 0 <= y <= 500


def test_world_date_line_edges_do_not_make_false_middle_line():
    paths = project_paths(((179, 10), (-179, 10)), View(), 1000, 500)
    assert len(paths) == 2
    assert all(abs(path[0][0] - path[-1][0]) < 10 for path in paths)
    assert all(all(x < 10 or x > 990 for x, y in path) for path in paths)


def test_date_line_centered_view_is_one_short_visible_path():
    view = View(-180, 10, 10)
    paths = project_paths(((179, 10), (-179, 10)), view, 1000, 500)
    assert len(paths) == 1 and abs(paths[0][0][0] - paths[0][-1][0]) == pytest.approx(200)


def test_segments_are_never_joined():
    a = project_paths(((0, 0), (1, 1)), View(), 1000, 500)
    b = project_paths(((20, 20), (21, 21)), View(), 1000, 500)
    assert len(a) == len(b) == 1 and a[0][-1] != b[0][0]
    assert connected_length_m(((P(0, 0),), (P(50, 50),))) == 0


def test_approximate_length_includes_only_within_segment_edges():
    assert connected_length_m(((P(0, 0), P(0, 1)), (P(50, 50),))) == pytest.approx(
        111194.9266, abs=0.01
    )


def test_single_point_fit_and_poles_finite():
    for point in (P(90, 179), P(-90, -180), P(0, 0)):
        view = fit_points((point,), 500, 400)
        x, y = view.position(point.longitude, point.latitude, 500, 400)
        assert (x, y) == pytest.approx((250, 200))
        assert view.span >= MIN_SPAN


def test_empty_fit_is_world():
    assert fit_points((), 500, 400) == View()


@pytest.mark.parametrize("factor", [0, -1, float("nan"), float("inf"), True])
def test_invalid_zoom_rejected(factor):
    with pytest.raises(ValueError):
        View().zoom(factor)


def test_zoom_and_pan_are_clamped_and_date_line_wrapped():
    assert View().zoom(0.1).span == 360
    assert View().zoom(1e50).span == MIN_SPAN
    v = View(179, 89, 360).pan(-100, 10000, 1000, 500)
    assert -180 <= v.longitude < 180 and v.latitude == 90
    assert View(0, 0, 180).pan(0, 0, 1000, 500) == View(0, 0, 180)


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ((-10, 50), (110, 50), ((0, 50), (100, 50))),
        ((50, -10), (50, 110), ((50, 0), (50, 100))),
        ((-10, -10), (-1, -1), None),
        ((10, 10), (10, 10), ((10, 10), (10, 10))),
    ],
)
def test_clipping_cases(a, b, expected):
    assert clip_line(a, b, 100, 100) == expected


def test_extreme_zoom_keeps_every_render_coordinate_inside_canvas():
    view = View(0, 0, MIN_SPAN)
    paths = project_paths(((-100, -80), (100, 80), (0, 0), (0, 90)), view, 1000, 500)
    assert all(
        math.isfinite(x) and 0 <= x <= 1000 and math.isfinite(y) and 0 <= y <= 500
        for p in paths
        for x, y in p
    )


def test_randomized_fit_encloses_all_short_arc_points():
    rng = random.Random(7)
    for _ in range(100):
        lon = rng.uniform(-180, 180)
        lat = rng.uniform(-60, 60)
        points = tuple(
            P(lat + rng.uniform(-10, 10), wrap(lon + rng.uniform(-10, 10))) for _ in range(12)
        )
        view = fit_points(points, 900, 450)
        for point in points:
            x, y = view.position(point.longitude, point.latitude, 900, 450)
            assert 0 <= x <= 900 and 0 <= y <= 450


def test_sampling_is_bounded_and_retains_shown_segment_endpoints():
    segments = tuple(tuple(P(s, i / 10000) for i in range(5000)) for s in range(10))
    shown = sample_segments(segments)
    assert sum(map(len, shown)) <= DISPLAY_POINTS
    for original, sampled in zip(segments, shown):
        assert sampled[0] == original[0] and sampled[-1] == original[-1]
    assert segments[0][1234].longitude == 0.1234


def test_too_many_segments_omits_whole_trailing_segments_not_connections():
    segments = tuple((P(i / 1000, 0), P(i / 1000, 1)) for i in range(10000))
    shown = sample_segments(segments, budget=7)
    assert sum(map(len, shown)) <= 7
    assert len(shown) == 3
    assert shown == segments[:3]


def test_singleton_is_retained():
    point = P(1, 2)
    assert sample_segments(((point,),), budget=1) == ((point,),)


@pytest.mark.parametrize("budget", [0, 8001, -1, True])
def test_invalid_preview_budgets_rejected(budget):
    with pytest.raises(ValueError):
        sample_segments(((P(0, 0),),), budget=budget)
