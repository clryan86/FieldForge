"""Native Tk rendering checks using synthetic geometry, not geographic coverage."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from test_gps_desktop import root as root

from fieldforge.navigation.map_view import Viewport
from fieldforge.navigation.osm_source import StreetFeature, StreetSource
from fieldforge.navigation.regional_index import IndexResults
from fieldforge.navigation.route_overlay import route_segments
from fieldforge.ui import street_source
from fieldforge.ui.regional_index import RegionalIndexWindow


def source(features):
    return StreetSource('SYNTHETIC rendering regression', '0' * 64, 0,
                        0, 0, 0, 0, 0, 0, 0, None, tuple(features))


def feature(view, ident, points, *, name=None, kind='highway=residential'):
    geometry = []
    for x, y in points:
        latitude, longitude = view.at_pixel(x, y)
        geometry.append((longitude, latitude))
    return StreetFeature(ident, name or ident, kind, tuple(geometry), ())


@pytest.fixture
def viewers(root):
    root.withdraw()
    windows = []

    def make(window_type=street_source.StreetSourceWindow):
        window = window_type(root)
        windows.append(window)
        root.update()
        if window._resize_id is not None:
            window.after_cancel(window._resize_id)
            window._resize_id = None
        window.view = Viewport(40, -70, 14, *window.size())
        window.source = source(())
        return window

    yield make
    for window in windows:
        window.close()
        window._worker.shutdown(wait=True, cancel_futures=True)


def geometry_items(window, ident):
    return tuple(item for item in window.canvas.find_withtag(ident)
                 if 'map-geometry' in window.canvas.gettags(item))


def label_items(window, ident=None):
    return tuple(item for item in window.canvas.find_withtag('map-label')
                 if ident is None or ident in window.canvas.gettags(item))


def overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def segments(window, ident):
    result = []
    for item in geometry_items(window, ident):
        if window.canvas.type(item) == 'line':
            coords = window.canvas.coords(item)
            points = list(zip(coords[::2], coords[1::2]))
            result.extend(zip(points, points[1:]))
    return result


def test_road_layer_stays_above_point_water_and_building_geometry(viewers):
    window = viewers()
    view = window.view
    x, y = view.width / 2, view.height / 2
    road = feature(view, 'way/1', [(x - 100, y), (x + 100, y)])
    point = feature(view, 'node/2', [(x, y)], kind='amenity=bench')
    water = feature(view, 'way/3', [(x, y - 100), (x, y + 100)], kind='waterway=stream')
    building = feature(view, 'way/4', [(x - 80, y), (x + 80, y)], kind='building=yes')
    # The old source-order renderer put every later object over this road.
    window.source = source((road, point, water, building))
    window.draw()
    stack = window.canvas.find_all()
    ranks = [stack.index(geometry_items(window, f.id)[0])
             for f in (building, water, point, road)]
    assert ranks == sorted(ranks)
    at_crossing = window.canvas.find_overlapping(x - 1, y - 1, x + 1, y + 1)
    assert at_crossing[-1] == geometry_items(window, road.id)[0]


def test_roads_get_geometry_budget_before_unselected_area_outlines(viewers, monkeypatch):
    window = viewers()
    view = window.view
    monkeypatch.setattr(street_source, 'MAX_DRAW_SEGMENTS', 1)
    area = feature(view, 'way/1', [(50, 140), (250, 140)], kind='building=yes')
    road = feature(view, 'way/2', [(50, 240), (250, 240)])
    window.source = source((area, road))
    window.draw()
    assert geometry_items(window, road.id)
    assert not geometry_items(window, area.id)
    assert 'background drawing limit reached' in window.status.get()
    assert 'DRAW LIMITED' in window.canvas.itemcget('caption', 'text')


def test_actual_long_text_bounds_do_not_overlap_each_other_or_caption(viewers):
    window = viewers()
    view = window.view
    # These anchors beat the old 95px distance check, but these wide-font names
    # extend far beyond 95px. Test actual native glyph bounds, not string lengths.
    window.source = source(tuple(
        feature(view, f'node/{i}', [(100 + 110 * i, 180)],
                name=f'WWWW West Waterway Warehouse {i}', kind='place=locality')
        for i in range(4)))
    window.draw()
    boxes = [window.canvas.bbox(item) for item in label_items(window)]
    assert boxes
    caption = window.canvas.bbox('caption')
    for i, box in enumerate(boxes):
        assert not overlap(box, caption)
        assert all(not overlap(box, other) for other in boxes[i + 1:])
        assert 0 <= box[0] < box[2] <= view.width
        assert 0 <= box[1] < box[3] <= view.height


def test_selected_geometry_and_label_survive_both_ordinary_budgets(viewers, monkeypatch):
    window = viewers()
    view = window.view
    monkeypatch.setattr(street_source, 'MAX_DRAW_SEGMENTS', 1)
    monkeypatch.setattr(street_source, 'MAX_LABELS', 0)
    first = feature(view, 'way/1', [(50, 140), (250, 140)], name='Ordinary road')
    omitted = feature(view, 'way/2', [(50, 220), (250, 220)])
    selected = feature(view, 'way/3', [(50, 310), (150, 310), (250, 320)],
                       name='Selected road')
    window.source = source((first, omitted, selected))
    window.selected_id = selected.id
    window.draw()
    assert len(segments(window, selected.id)) == 2
    assert len(label_items(window)) == 1
    assert label_items(window, selected.id)
    assert all(float(window.canvas.itemcget(item, 'width')) == 5
               for item in geometry_items(window, selected.id))
    assert 'background drawing limit reached' in window.status.get()
    assert 'label limit reached' in window.status.get()


def test_selected_label_reserves_measured_space_before_crowded_names(viewers):
    window = viewers()
    view = window.view
    point = (view.width / 2, view.height / 2)
    nearby = tuple(feature(view, f'node/{i}', [point],
                           name=f'Nearby Warehouse {i}', kind='amenity=school') for i in range(7))
    selected = feature(view, 'node/9', [point], name='Selected Warehouse', kind='amenity=school')
    window.source = source((*nearby, selected))
    window.selected_id = selected.id
    window.draw()
    chosen, = label_items(window, selected.id)
    selected_box = window.canvas.bbox(chosen)
    for item in label_items(window):
        if item != chosen:
            assert not overlap(selected_box, window.canvas.bbox(item))
    assert window.canvas.find_all()[-1] == chosen


def test_selected_long_line_draws_only_real_contiguous_segments_and_reports_partial(viewers, monkeypatch):
    window = viewers()
    view = window.view
    monkeypatch.setattr(street_source, 'MAX_SELECTED_SEGMENTS', 3)
    selected = feature(view, 'way/9', [(100 + 25 * i, 160 + (i % 2) * 40) for i in range(10)],
                       name='Selected long source feature')
    window.source = source((selected,))
    window.selected_id = selected.id
    window.draw()
    drawn = segments(window, selected.id)
    expected = tuple(zip(*[route_segments(selected.geometry, view)[0][i:] for i in (0, 1)]))
    assert len(drawn) == 3
    for actual, original in zip(drawn, expected[:3]):
        assert actual[0] == pytest.approx(original[0])
        assert actual[1] == pytest.approx(original[1])
    assert label_items(window, selected.id)
    assert 'selected feature is only partly drawn' in window.status.get()


def test_selected_label_uses_visible_clipped_segment_when_middle_node_is_outside(viewers):
    window = viewers()
    view = window.view
    selected = feature(view, 'way/9', [(-250, 210), (-100, 210), (view.width + 250, 210)],
                       name='Road crossing the view')
    assert not view.locations(selected.geometry[1][1], selected.geometry[1][0])
    window.source = source((selected,))
    window.selected_id = selected.id
    window.draw()
    assert segments(window, selected.id)
    item, = label_items(window, selected.id)
    box = window.canvas.bbox(item)
    assert 0 <= box[0] < box[2] <= view.width
    assert 0 <= box[1] < box[3] <= view.height


def test_chunk_boundaries_preserve_clipped_source_segments_and_never_join_gap(viewers, monkeypatch):
    window = viewers()
    view = window.view
    monkeypatch.setattr(street_source, 'PROJECTION_CHUNK_POINTS', 3)
    selected = feature(view, 'way/7', [
        (100, 160), (200, 160), (view.width + 200, 160),
        (view.width + 200, 300), (200, 300), (100, 300),
    ])
    window.source = source((selected,))
    window.selected_id = selected.id
    window.draw()
    actual = segments(window, selected.id)
    expected = [pair for line in route_segments(selected.geometry, view)
                for pair in zip(line, line[1:])]
    assert len(actual) == len(expected)
    for drawn, original in zip(actual, expected):
        assert drawn[0] == pytest.approx(original[0])
        assert drawn[1] == pytest.approx(original[1])
        assert drawn[0][1] == pytest.approx(drawn[1][1])


def test_date_line_chunk_projection_keeps_short_wrap_segments(viewers, monkeypatch):
    window = viewers()
    window.view = Viewport(0, 180, 4, *window.size())
    monkeypatch.setattr(street_source, 'PROJECTION_CHUNK_POINTS', 2)
    selected = StreetFeature('way/1', 'Date-line source', 'highway=service',
        ((178, 0), (179, 0), (-179, 0), (-178, 0)), ())
    window.source = source((selected,))
    window.selected_id = selected.id
    window.draw()
    drawn = segments(window, selected.id)
    assert len(drawn) == 3
    assert all(abs(b[0] - a[0]) < 25 for a, b in drawn)
    assert label_items(window, selected.id)


def test_marker_and_label_candidate_budgets_are_bounded_with_selected_point(viewers, monkeypatch):
    window = viewers()
    view = window.view
    monkeypatch.setattr(street_source, 'MAX_DRAW_MARKERS', 4)
    monkeypatch.setattr(street_source, 'MAX_LABEL_CANDIDATES', 2)
    points = tuple(feature(view, f'node/{i}', [(90 + 30 * i, 180)],
                           name=f'Source point {i}', kind='place=locality') for i in range(10))
    selected = feature(view, 'node/20', [(170, 310)], kind='place=locality')
    window.source = source((*points, selected))
    window.selected_id = selected.id
    window.draw()
    assert len(window.canvas.find_withtag('map-geometry')) == 5
    assert len(label_items(window)) <= 3
    # Even an unnamed selection gets its OSM ID as a persistent label.
    item, = label_items(window, selected.id)
    assert window.canvas.itemcget(item, 'text') == selected.id
    assert 'background drawing limit reached' in window.status.get()
    assert 'label limit reached' in window.status.get()


def test_tiny_viewport_keeps_selected_annotation_inside_actual_bounds(viewers):
    window = viewers()
    window.view = Viewport(40, -70, 14, 50, 50)
    selected = feature(window.view, 'node/1', [(0, 0)],
                       name='Wide Warehouse Name ' * 10, kind='place=locality')
    window.source = source((selected,))
    window.selected_id = selected.id
    window.draw()
    item, = label_items(window, selected.id)
    box = window.canvas.bbox(item)
    assert 0 <= box[0] < box[2] <= 50
    assert 0 <= box[1] < box[3] <= 50
    assert window.canvas.find_all()[-1] == item
    assert selected.name == 'Wide Warehouse Name ' * 10


def test_regional_page_reports_query_and_draw_limits_and_keeps_selection(viewers, monkeypatch):
    window = viewers(RegionalIndexWindow)
    view = window.view
    monkeypatch.setattr(street_source, 'MAX_DRAW_SEGMENTS', 1)
    road = feature(view, 'way/1', [(80, 180), (180, 180), (280, 180)], name='Page road')
    selected = feature(view, 'way/9', [(80, 300), (280, 300)], name='Selected search result')
    window.index = SimpleNamespace(metadata={'features': 5000})
    window.selected_id, window._selected_feature = selected.id, selected
    matches = IndexResults((selected,), False)
    page = IndexResults((road,), True)
    window.loaded_page((window.index, window.query.get(), view, matches, page))
    assert selected in window.source.features and selected not in window._viewport_features
    assert geometry_items(window, selected.id) and label_items(window, selected.id)
    caption = window.canvas.itemcget('caption', 'text')
    assert 'VIEW LIMITED' in caption and 'DRAW LIMITED' in caption
    assert 'LIMITED: zoom in' in window.summary.get()
    for item in label_items(window):
        assert not overlap(window.canvas.bbox(item), window.canvas.bbox('caption'))

    # A later complete page must clear both warnings rather than carry stale state.
    window.loaded_page((window.index, window.query.get(), view, matches, IndexResults((), False)))
    assert 'LIMITED' not in window.canvas.itemcget('caption', 'text')
    assert 'Display limited:' not in window.status.get()
    assert geometry_items(window, selected.id) and label_items(window, selected.id)
