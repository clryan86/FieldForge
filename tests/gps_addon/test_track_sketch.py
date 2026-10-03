import math

import pytest

from fieldforge_gps.track_sketch import sketch
from fieldforge_gps.tracks import TrackRecorder

from .test_tracks import point, recorder


def test_empty_sketch():
    result = sketch(TrackRecorder("serial").snapshot(), 800, 400)
    assert result.segments == () and result.shown_points == 0


@pytest.mark.parametrize("width,height", [(99, 400), (800, 0), (800.0, 400), (True, 400)])
def test_invalid_canvas_size(width, height):
    with pytest.raises(ValueError):
        sketch(TrackRecorder("serial").snapshot(), width, height)


def test_segments_and_endpoints_are_not_joined():
    r = recorder()
    r.append(point(), 0)
    r.append(point(1, lat=10.01), 1)
    r.gap()
    r.append(point(2, lon=20.02), 2)
    p = sketch(r.snapshot(), 800, 400)
    assert [len(seg) for seg in p.segments] == [2, 1]
    assert p.shown_points == 3 and p.total_points == 3
    for segment in p.segments:
        for x, y in segment:
            assert 40 <= x <= 760 and 40 <= y <= 360


def test_dateline_short_crossing_does_not_become_long_wrong_direction():
    r = recorder()
    r.append(point(lat=0, lon=179.999), 0)
    r.append(point(1, lat=0, lon=-179.999), 1)
    p = sketch(r.snapshot(), 800, 400)
    assert p.segments[0][1][0] > p.segments[0][0][0]


def test_single_polar_point_and_identical_points_remain_finite():
    r = recorder()
    r.append(point(lat=90, lon=180), 0)
    r.append(point(1, lat=90, lon=180), 1)
    p = sketch(r.snapshot(), 800, 400)
    assert p.segments[0][0] == pytest.approx((400, 200))
    assert all(math.isfinite(value) for seg in p.segments for xy in seg for value in xy)


def test_max_capacity_preview_bounded_export_history_unchanged():
    r = recorder()
    for i in range(50000):
        r.append(point(i, lat=10 + i / 1e6, lon=20 + i / 1e6), i)
    t = r.snapshot()
    p = sketch(t, 800, 400)
    assert p.shown_points <= 5000 and p.total_points == 50000
    assert len(t.segments[0]) == 50000 and t.summary.state == "finished"
    assert p.segments[0][0] != p.segments[0][-1]


def test_many_segments_bounded_without_connecting_omitted_segments():
    r = recorder()
    for i in range(2000):
        r.gap()
        r.append(point(i, lat=10 + i / 1e5), i)
    p = sketch(r.snapshot(), 800, 400)
    assert p.shown_segments == 1000 and p.total_segments == 2000
    assert all(len(seg) == 1 for seg in p.segments)
