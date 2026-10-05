"""Disk-index regression tests. Geographic coverage is not inferred from fixtures."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import struct
import zipfile
from collections import Counter
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from test_osm_source import (
    SAMPLE,
    binary,
    block,
    fixture,
    header,
    integer,
    node,
    packed,
    primitive,
    way,
    zz,
)

from fieldforge.navigation import osm_source as osm
from fieldforge.navigation import regional_index as regional
from fieldforge.navigation.map_view import Viewport
from fieldforge.navigation.mbtiles import MapCancelled
from fieldforge.navigation.pbf_stream import IndexLimits, PBFStream


def build(tmp_path, raw=None, **kwargs):
    source = tmp_path / 'source.osm.pbf'
    source.write_bytes(fixture() if raw is None else raw)
    return regional.prepare_index(source, tmp_path / 'map.ffmap', **kwargs)


def change(index, sql, args=()):
    with sqlite3.connect(index.path) as con:
        con.execute(sql, args)
    return replace(index, fingerprint=regional.signature(index.path))


def crowded_index(tmp_path, *, points=900, roads=900, areas=900,
                  center=(-70, 40), point_center=None):
    """Prepare actual PBF with points first, then buildings, then highway ways."""
    lon, lat = center
    point_lon, point_lat = point_center or center
    strings = ('', 'highway', 'residential', 'name', 'Map Street',
               'building', 'yes', 'crossing')
    group = (binary(1, node(1, lon, lat)) +
             binary(1, node(2, lon + .001, lat + .001)) +
             binary(1, node(3, lon - .001, lat + .001)))
    # Highway-tagged points must not take the slots reserved for road lines.
    tags = packed(2, (1, 3)) + packed(3, (7, 4))
    group += b''.join(binary(1, node(1000 + i, point_lon, point_lat, tags))
                      for i in range(points))
    group += b''.join(binary(3, way(i + 1, (1, 2, 3, 1), keys=(5, 3), vals=(6, 4)))
                      for i in range(areas))
    group += b''.join(binary(3, way(areas + i + 1)) for i in range(roads))
    return build(tmp_path, header() + primitive(group, strings))


def geometry_counts(features):
    return Counter('point' if len(f.geometry) == 1 else
                   'road' if f.kind.startswith('highway=') else 'area' for f in features)


def test_historical_geometry_matches_existing_reader_exactly(tmp_path):
    before = SAMPLE.read_bytes()
    index = regional.prepare_index(SAMPLE, tmp_path / 'history.ffmap')
    expected = {f.id: f for f in osm.read_street_source(SAMPLE).features}
    actual = {f.id: f for f in regional.search_index(index, '', limit=1000).features}
    assert actual == expected and len(actual) == 51
    assert SAMPLE.read_bytes() == before
    assert index.metadata['source_sha256'] == hashlib.sha256(before).hexdigest()
    assert index.metadata['replication_timestamp'] is None
    assert index.metadata['state'] == 'visual-search-only'
    assert index.metadata['nodes'] == 290
    reopened = regional.inspect_index(index.path)
    assert len(regional.search_index(reopened, 'Wellfield Road').features) == 1
    assert not list(tmp_path.glob('.fieldforge-index-*'))


@pytest.mark.parametrize('dense', (False, True))
@pytest.mark.parametrize('fts', (False, True))
def test_streamed_geometry_dense_raw_and_search_fallback(tmp_path, dense, fts):
    index = build(tmp_path, fixture(dense=dense), use_fts=fts)
    assert index.metadata['fts'] is fts
    found = regional.search_index(index, 'Map Street')
    assert len(found.features) == 2 and not found.limited
    road = next(f for f in found.features if f.id == 'way/10')
    assert road.geometry == ((-70, 40), (-69.999, 40.001))
    assert regional.inspect_index(index.path).metadata == index.metadata


def test_explicit_address_tags_are_searchable_with_source_coordinates(tmp_path):
    strings = ('', 'addr:housenumber', '123A', 'addr:street', 'Map Street',
               'addr:city', 'Testville')
    tags = packed(2, (1, 3, 5)) + packed(3, (2, 4, 6))
    raw = header() + primitive(binary(1, node(7, -70, 40, tags)), strings)
    index = build(tmp_path, raw)

    matches = regional.search_index(index, '123A Map Street')
    assert len(matches.features) == 1 and not matches.limited
    feature, = matches.features
    assert feature.kind == 'address tags'
    assert feature.name == '123A Map Street'
    assert index.metadata['address_features'] == 1
    assert regional.feature_coordinate(feature) == (40.0, -70.0, True)
    assert not regional.search_index(index, '124 Map Street').features


def test_nonpoint_coordinate_is_only_feature_bounds_center():
    feature = osm.StreetFeature('way/2', 'Building', 'building=yes',
                                ((10, 20), (14, 24), (12, 22)), ())
    assert regional.feature_coordinate(feature) == (22.0, 12.0, False)


def test_source_may_be_out_of_order_and_missing_ways_are_not_connected(tmp_path):
    raw = header() + primitive(binary(3, way())) + primitive(
        binary(1, node(2, 10, 20)) + binary(1, node(1, 11, 21)))
    index = build(tmp_path, raw)
    assert regional.search_index(index, '').features[0].geometry == ((11, 21), (10, 20))
    other = tmp_path / 'other'
    other.mkdir()
    missing = build(other, fixture(missing=True))
    assert missing.metadata['missing_node_ways'] == 1
    assert all(f.id.startswith('node/') for f in regional.search_index(missing, '').features)


def test_contact_and_contributor_values_not_in_output(tmp_path):
    tags = packed(2, [1, 3, 5]) + packed(3, [2, 4, 6])
    strings = ('', 'name', 'Public feature', 'phone', 'SECRET-TELEPHONE', 'email', 'SECRET-MAIL')
    raw = header() + primitive(binary(1, node(1, 10, 20, tags)), strings)
    index = build(tmp_path, raw)
    content = index.path.read_bytes()
    assert b'SECRET-TELEPHONE' not in content and b'SECRET-MAIL' not in content
    assert regional.search_index(index, '').features[0].tags == (('name', 'Public feature'),)
    assert 'source.osm.pbf' in index.metadata['source_name']
    assert str(tmp_path) not in json.dumps(index.metadata)


def test_index_works_without_source_after_copy(tmp_path):
    index = build(tmp_path)
    (tmp_path / 'source.osm.pbf').unlink()
    copy = tmp_path / 'copy space \u00e9.ffmap'
    copy.write_bytes(index.path.read_bytes())
    before = copy.read_bytes()
    reopened = regional.inspect_index(copy)
    assert regional.search_index(reopened, 'Map Street').features
    assert copy.read_bytes() == before
    assert not list(tmp_path.glob('*-journal'))


@pytest.mark.parametrize('raw', [
    b'bad', b'\x00\x00\x00\x00', fixture()[:-1], fixture() + b'!',''.encode(),
    primitive(b''), header(),
    header(required=('OsmSchema-V0.6', 'HistoricalInformation')) + primitive(b''),
    header() + header() + primitive(b''),
    header() + block(b'OtherBlock', b''),
    header() + primitive(binary(5, b'')),
    header() + primitive(binary(3, way(extra=integer(9, 1)))),
])
def test_malformed_inputs_leave_no_output_or_temporaries(tmp_path, raw):
    with pytest.raises((ValueError, OSError)):
        build(tmp_path, raw)
    assert (tmp_path / 'source.osm.pbf').read_bytes() == raw
    assert not (tmp_path / 'map.ffmap').exists()
    assert not list(tmp_path.glob('.fieldforge-index-*'))


@pytest.mark.parametrize('kind', ('node', 'way', 'relation'))
def test_duplicate_id_across_blocks_is_refused(tmp_path, kind):
    if kind == 'node':
        group = binary(1, node(1, 10, 20))
    elif kind == 'way':
        group = binary(3, way())
    else:
        group = binary(4, integer(1, 500))
    with pytest.raises(ValueError, match='Duplicate'):
        build(tmp_path, header() + primitive(group) + primitive(group))
    assert not (tmp_path / 'map.ffmap').exists()


@pytest.mark.parametrize('limits', [
    IndexLimits(file_bytes=10), IndexLimits(inflated_bytes=10),
    IndexLimits(blocks=1), IndexLimits(nodes=1),
    IndexLimits(references=1), IndexLimits(way_points=1),
    IndexLimits(features=1), IndexLimits(database_bytes=4096),
])
def test_explicit_decode_and_disk_budgets(tmp_path, limits):
    with pytest.raises(ValueError):
        build(tmp_path, limits=limits)
    assert not (tmp_path / 'map.ffmap').exists()
    assert not list(tmp_path.glob('.fieldforge-index-*'))


@pytest.mark.parametrize('value', [0, -1, True, 0.5, '100'])
def test_invalid_limits_rejected(value):
    with pytest.raises(ValueError):
        IndexLimits(nodes=value)


def test_cancellation_before_decode(tmp_path):
    event = Event()
    event.set()
    with pytest.raises(MapCancelled):
        build(tmp_path, cancel=event)
    assert not (tmp_path / 'map.ffmap').exists()


@pytest.mark.parametrize('stage', (0, 70))
def test_cancel_during_decode_and_geometry_removes_temporaries(tmp_path, stage):
    event = Event()
    with pytest.raises(MapCancelled):
        build(tmp_path, cancel=event, progress=lambda current, _: event.set() if current >= stage else None)
    assert not (tmp_path / 'map.ffmap').exists()
    assert not list(tmp_path.glob('.fieldforge-index-*'))


def test_bad_checksum_leaves_previous_file_and_source_unchanged(tmp_path):
    with pytest.raises(ValueError, match='checksum'):
        build(tmp_path, expected_sha256='0' * 64)
    assert not (tmp_path / 'map.ffmap').exists()
    index = build(tmp_path)
    before = index.path.read_bytes()
    with pytest.raises(FileExistsError):
        regional.prepare_index(tmp_path / 'source.osm.pbf', index.path)
    assert index.path.read_bytes() == before


def test_atomic_publish_never_clobbers_racing_target(tmp_path, monkeypatch):
    real_link = os.link
    platform = SimpleNamespace(**vars(os))
    platform.name = 'posix'
    monkeypatch.setattr(regional, 'os', platform)

    def raced(source, target):
        Path(target).write_bytes(b'OTHER-WRITER')
        return real_link(source, target)

    monkeypatch.setattr(regional.os, 'link', raced)
    with pytest.raises(FileExistsError):
        build(tmp_path)
    assert (tmp_path / 'map.ffmap').read_bytes() == b'OTHER-WRITER'
    assert not list(tmp_path.glob('.fieldforge-index-*'))


def test_no_hardlink_support_is_explicit_and_cleans_up(tmp_path, monkeypatch):
    platform = SimpleNamespace(**vars(os))
    platform.name = 'posix'
    monkeypatch.setattr(regional, 'os', platform)

    def fail(*_args):
        raise OSError('no hard links')
    monkeypatch.setattr(regional.os, 'link', fail)
    with pytest.raises(OSError, match='hard links'):
        build(tmp_path)
    assert not (tmp_path / 'map.ffmap').exists()
    assert not list(tmp_path.glob('.fieldforge-index-*'))


def test_import_archive_validates_and_extracts_only_the_regional_index(tmp_path):
    index = build(tmp_path)
    archive = tmp_path / 'regional-pack.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as package:
        package.write(index.path, 'South Dakota/map.ffmap')
        package.writestr('South Dakota/source.osm.pbf', b'not extracted')
        package.writestr('South Dakota/rights.txt', '© OpenStreetMap contributors')
    output = tmp_path / 'output'
    output.mkdir()
    target = output / 'imported.ffmap'
    imported = regional.import_archive(archive, target)
    assert imported.path == target
    assert imported.metadata == index.metadata
    assert regional.search_index(imported, 'Map Street').features
    assert not (output / 'source.osm.pbf').exists()
    assert not list(tmp_path.glob('.fieldforge-index-*'))


@pytest.mark.parametrize('member_name', ('../map.ffmap', 'folder/../map.ffmap'))
def test_import_archive_rejects_unsafe_index_paths(tmp_path, member_name):
    index = build(tmp_path)
    archive = tmp_path / 'unsafe.zip'
    with zipfile.ZipFile(archive, 'w') as package:
        package.writestr(member_name, index.path.read_bytes())
    with pytest.raises(ValueError, match='safe regular file'):
        regional.import_archive(archive, tmp_path / 'imported.ffmap')
    assert not (tmp_path / 'imported.ffmap').exists()
    assert not list(tmp_path.glob('.fieldforge-index-*'))


def test_import_archive_requires_one_index_and_never_replaces(tmp_path):
    index = build(tmp_path)
    archive = tmp_path / 'duplicate.zip'
    with zipfile.ZipFile(archive, 'w') as package:
        package.write(index.path, 'a/map.ffmap')
        package.write(index.path, 'b/map.ffmap')
    target = tmp_path / 'new.ffmap'
    with pytest.raises(ValueError, match='exactly one'):
        regional.import_archive(archive, target)
    target.write_bytes(b'keep')
    with pytest.raises(FileExistsError):
        regional.import_archive(archive, target)
    assert target.read_bytes() == b'keep'


def test_cancel_archive_import_cleans_partial_file(tmp_path):
    index = build(tmp_path)
    archive = tmp_path / 'regional-pack.zip'
    with zipfile.ZipFile(archive, 'w') as package:
        package.write(index.path, 'map.ffmap')
    event = Event()
    with pytest.raises(MapCancelled):
        regional.import_archive(archive, tmp_path / 'cancelled.ffmap', cancel=event,
                                progress=lambda current, _total: event.set() if current else None)
    assert not (tmp_path / 'cancelled.ffmap').exists()
    assert not list(tmp_path.glob('.fieldforge-index-*'))


def test_changed_source_before_publication_refused(tmp_path):
    path = tmp_path / 'source.osm.pbf'

    def mutate(current, _):
        if current == 70:
            with path.open('ab') as f:
                f.write(b'changed')

    with pytest.raises(ValueError, match='changed'):
        build(tmp_path, progress=mutate)
    assert not (tmp_path / 'map.ffmap').exists()


def test_read_only_never_creates_missing_index_or_edits_household(tmp_path):
    index = build(tmp_path)
    with pytest.raises(FileNotFoundError):
        regional.inspect_index(tmp_path / 'missing.ffmap')
    household = tmp_path / 'household.db'
    with sqlite3.connect(household) as con:
        con.execute('CREATE TABLE private (secret TEXT)')
        con.execute("INSERT INTO private VALUES ('private record')")
    before = household.read_bytes()
    with pytest.raises(ValueError, match='Not a supported'):
        regional.inspect_index(household)
    assert household.read_bytes() == before
    with pytest.raises(ValueError, match='.ffmap'):
        regional.prepare_index(tmp_path / 'source.osm.pbf', household)
    assert regional.search_index(index, 'private').features == ()


def test_changed_index_refused_until_explicitly_reopened(tmp_path):
    index = build(tmp_path)
    updated = change(index, "UPDATE features SET name='New label' WHERE osm_id='way/10'")
    with pytest.raises(ValueError, match='changed on disk'):
        regional.search_index(index, 'Map')
    # SQLite checks structure, not publisher authenticity or semantic label correctness.
    assert regional.inspect_index(updated.path).metadata['features'] == 2


@pytest.mark.parametrize('suffix', ('-journal', '-wal', '-shm'))
def test_index_with_active_sidecar_refused(tmp_path, suffix):
    index = build(tmp_path)
    Path(str(index.path) + suffix).write_bytes(b'active')
    with pytest.raises(ValueError, match='sidecar'):
        regional.inspect_index(index.path)


def test_views_and_wrong_schema_refused(tmp_path):
    index = build(tmp_path)
    index = change(index, 'CREATE VIEW extra AS SELECT 1')
    with pytest.raises(ValueError, match='Views/triggers'):
        regional.inspect_index(index.path)


@pytest.mark.parametrize('sql', ['PRAGMA user_version=99', 'PRAGMA application_id=12'])
def test_wrong_format_refused(tmp_path, sql):
    index = build(tmp_path)
    index = change(index, sql)
    with pytest.raises(ValueError, match='Not a supported'):
        regional.inspect_index(index.path)


def test_broken_feature_counts_detected(tmp_path):
    index = build(tmp_path)
    index = change(index, 'DELETE FROM feature_bounds WHERE fid=1')
    with pytest.raises(ValueError, match='count'):
        regional.inspect_index(index.path)


def test_missing_spatial_record_not_hidden_by_equal_count(tmp_path):
    index = build(tmp_path)
    index = change(index, 'UPDATE feature_bounds SET fid=999 WHERE fid=1')
    with pytest.raises(ValueError, match='missing spatial'):
        regional.inspect_index(index.path)


@pytest.mark.parametrize('geometry', [b'x', struct.pack('<dd', float('nan'), 4),
                                     struct.pack('<dd', 200, 4), struct.pack('<dd', 1, 89)])
def test_bad_feature_geometry_refused_at_query(tmp_path, geometry):
    index = build(tmp_path)
    index = change(index, 'UPDATE features SET geometry=?', (geometry,))
    with pytest.raises(ValueError, match='feature'):
        regional.search_index(index, '')


def test_polar_and_date_line_ways_reported_not_invented(tmp_path):
    nodes = (binary(1, node(1, 179, 0)) + binary(1, node(2, -179, 0)) +
             binary(1, node(3, 10, 89)) + binary(1, node(4, 11, 89)))
    roads = binary(3, way(10, (1, 2))) + binary(3, way(11, (3, 4)))
    index = build(tmp_path, header() + primitive(nodes + roads))
    assert index.metadata['features'] == 0
    assert index.metadata['polar_features'] == 1
    assert index.metadata['dateline_features'] == 1
    assert not regional.search_index(index, '').features
    assert regional.inspect_index(index.path).metadata['bounds'] is None


def test_relation_restrictions_recorded_not_applied(tmp_path):
    tags = packed(2, [1]) + packed(3, [2])
    member = packed(8, [3]) + packed(9, [zz(10)]) + packed(10, [1])
    raw = header() + primitive(binary(4, integer(1, 20) + tags + member),
                               ('', 'type', 'restriction', 'from'))
    index = build(tmp_path, raw)
    assert index.metadata['relations'] == index.metadata['restrictions'] == 1
    assert not regional.search_index(index, '').features


def test_query_literals_unicode_limits_and_fts_prefix(tmp_path):
    index = build(tmp_path)
    assert len(regional.search_index(index, 'Ｍａｐ STREET').features) == 2
    assert len(regional.search_index(index, 'str').features) == 2
    for query in ('***', '\" OR 1=1 --', 'missing', '<script>alert(1)</script>'):
        assert not regional.search_index(index, query).features
    assert regional.search_index(index, '', limit=1).limited
    assert not regional.search_index(index, 'missing', limit=1).limited
    with pytest.raises(ValueError):
        regional.search_index(index, 'x' * 201)
    with pytest.raises(ValueError):
        regional.search_index(index, 'a ' * 17)


@pytest.mark.parametrize('limit', [0, 1001, True, 1.2])
def test_bad_query_limits(tmp_path, limit):
    index = build(tmp_path)
    with pytest.raises(ValueError):
        regional.search_index(index, '', limit=limit)
    with pytest.raises(ValueError):
        regional.visible_index(index, (-71, 39, -69, 41), limit=limit)


@pytest.mark.parametrize('bounds', [(-200, 0, 10, 20), (10, 20, 5, 30), (1, -89, 2, 0),
                                    (1, 2, float('nan'), 4), (True, 0, 1, 1), (1, 2)])
def test_invalid_query_bounds(tmp_path, bounds):
    index = build(tmp_path)
    with pytest.raises(ValueError):
        regional.visible_index(index, bounds)


def test_spatial_query_empty_and_subregion(tmp_path):
    index = build(tmp_path)
    assert regional.visible_index(index, (10, 10, 20, 20)).features == ()
    assert len(regional.visible_index(index, (-70.001, 39.999, -69.999, 40.001)).features) == 2
    view = Viewport(40, -70, 16, 800, 400)
    assert regional.viewport_index(index, view).features
    assert len(regional.view_boxes(Viewport(0, 179.9, 4, 800, 400))) == 2
    assert regional.view_boxes(Viewport(0, 0, 0, 800, 400))[0][0::2] == (-180, 180)


def test_crowded_view_reserves_roads_areas_and_points_without_changing_search(tmp_path):
    index = crowded_index(tmp_path)
    bounds = (-70.01, 39.99, -69.99, 40.01)
    found = regional.visible_index(index, bounds)

    assert len(found.features) == 700 and found.limited
    assert geometry_counts(found.features) == {'road': 350, 'area': 175, 'point': 175}
    assert len({f.id for f in found.features}) == 700
    assert regional.visible_index(index, bounds) == found
    # Ways remain complete, including the closed building boundary.
    assert next(f for f in found.features if f.kind == 'highway=residential').geometry == (
        (-70, 40), (-69.999, 40.001))
    assert next(f for f in found.features if f.kind == 'building=yes').geometry == (
        (-70, 40), (-69.999, 40.001), (-70.001, 40.001), (-70, 40))
    # Text search keeps its original source/fid order and complete matching rules.
    searched = regional.search_index(index, 'Map Street', limit=700)
    assert geometry_counts(searched.features) == {'point': 700} and searched.limited


@pytest.mark.parametrize('limit,expected', [
    (1, {'road': 1}),
    (2, {'road': 1, 'point': 1}),
    (3, {'road': 1, 'point': 1, 'area': 1}),
    (4, {'road': 2, 'point': 1, 'area': 1}),
    (5, {'road': 3, 'point': 1, 'area': 1}),
])
def test_small_view_limits_keep_deterministic_geometry_priority(tmp_path, limit, expected):
    index = crowded_index(tmp_path, points=6, roads=6, areas=6)
    found = regional.visible_index(index, (-71, 39, -69, 41), limit=limit)
    assert geometry_counts(found.features) == expected
    assert len(found.features) == limit and found.limited


@pytest.mark.parametrize('points,roads,areas,expected,limited', [
    (12, 0, 0, {'point': 9}, True),
    (0, 12, 0, {'road': 9}, True),
    (0, 0, 12, {'area': 9}, True),
    (12, 2, 0, {'point': 7, 'road': 2}, True),
    (2, 12, 0, {'point': 2, 'road': 7}, True),
    (0, 2, 2, {'road': 2, 'area': 2}, False),
    (3, 3, 3, {'point': 3, 'road': 3, 'area': 3}, False),
    (0, 0, 0, {}, False),
])
def test_sparse_geometry_pools_refill_unused_slots(tmp_path, points, roads, areas,
                                                  expected, limited):
    index = crowded_index(tmp_path, points=points, roads=roads, areas=areas)
    found = regional.visible_index(index, (-71, 39, -69, 41), limit=9)
    assert geometry_counts(found.features) == expected
    assert found.limited is limited


def test_view_geometry_budget_skips_large_paths_and_keeps_whole_smaller_features(tmp_path,
                                                                              monkeypatch):
    index = crowded_index(tmp_path, points=6, roads=6, areas=6)
    # First road is valid but cannot fit; subsequent short roads still can.
    index = change(index, "UPDATE features SET geometry=? WHERE osm_id='way/7'",
                   (struct.pack('<dd', -70, 40) * 10,))
    monkeypatch.setattr(regional, 'MAX_QUERY_POINTS', 8)
    found = regional.visible_index(index, (-71, 39, -69, 41), limit=8)
    assert geometry_counts(found.features) == {'road': 1, 'area': 1, 'point': 2}
    assert sum(len(f.geometry) for f in found.features) == 8 and found.limited
    assert 'way/7' not in {f.id for f in found.features}
    assert next(f for f in found.features if f.kind == 'building=yes').geometry[0] == (
        next(f for f in found.features if f.kind == 'building=yes').geometry[-1])


def test_view_decodes_only_selected_geometry_with_maximum_supported_feature_limit(tmp_path,
                                                                                monkeypatch):
    index = crowded_index(tmp_path)
    real_feature = regional._feature
    decoded = []

    def record(row):
        decoded.append(row[0])
        return real_feature(row)

    monkeypatch.setattr(regional, '_feature', record)
    found = regional.visible_index(index, (-71, 39, -69, 41), limit=1000)
    assert len(found.features) == len(decoded) == 1000 and found.limited
    assert geometry_counts(found.features) == {'road': 500, 'area': 250, 'point': 250}
    assert set(decoded) == {f.id for f in found.features}
    assert sum(len(f.geometry) for f in found.features) <= regional.MAX_QUERY_POINTS


@pytest.mark.parametrize('geometry', [b'x', b'x' * 17, 'x' * 16, b'x' * 160016,
                                     struct.pack('<dd', float('nan'), 4),
                                     struct.pack('<dd', 200, 4), struct.pack('<dd', 1, 89)])
def test_view_rejects_invalid_geometry_instead_of_skipping_it_as_over_budget(tmp_path,
                                                                           geometry):
    index = build(tmp_path)
    index = change(index, 'UPDATE features SET geometry=?', (geometry,))
    with pytest.raises(ValueError, match='feature'):
        regional.visible_index(index, (-71, 39, -69, 41))
    with pytest.raises(ValueError, match='feature'):
        regional.viewport_index(index, Viewport(40, -70, 16, 800, 400))


def test_view_refines_outward_rounded_rtree_bounds(tmp_path):
    tags = packed(2, (3,)) + packed(3, (4,))
    index = build(tmp_path, header() + primitive(binary(1, node(1, 10.0000001, 20.0000001,
                                                             tags))))
    # SQLite's float32 spatial box overlaps, but the original coordinates do not.
    with sqlite3.connect(index.path) as con:
        assert con.execute('SELECT COUNT(*) FROM feature_bounds WHERE west<=10 AND south<=20'
                           ).fetchone()[0] == 1
    found = regional.visible_index(index, (9, 19, 10, 20))
    assert found.features == () and not found.limited
    assert len(regional.visible_index(index, (10, 20, 11, 21)).features) == 1


def test_wrapped_view_balances_geometry_across_both_longitude_boxes(tmp_path):
    index = crowded_index(tmp_path, points=800, roads=10, areas=10,
                          center=(-179.9, 0), point_center=(179.9, 0))
    view = Viewport(0, 179.9, 4, 800, 400)
    assert len(regional.view_boxes(view)) == 2
    found = regional.viewport_index(index, view)
    assert len(found.features) == 700 and found.limited
    assert geometry_counts(found.features) == {'road': 10, 'area': 10, 'point': 680}
    assert len({f.id for f in found.features}) == 700


def test_wrapped_view_deduplicates_before_counting_or_reporting_limits(tmp_path):
    tags = packed(2, (3,)) + packed(3, (4,))
    group = (binary(1, node(1, 179, 0, tags)) + binary(1, node(2, 0, 0)) +
             binary(1, node(3, -179, 0)) + binary(3, way(refs=(1, 2, 3))))
    index = build(tmp_path, header() + primitive(group))
    view = Viewport(0, 179.9, 4, 800, 400)
    found = regional.viewport_index(index, view)
    assert {f.id for f in found.features} == {'node/1', 'way/10'}
    assert len(found.features) == 2 and not found.limited


def test_cancelled_queries(tmp_path):
    index = build(tmp_path)
    event = Event()
    event.set()
    with pytest.raises(MapCancelled):
        regional.search_index(index, '', cancel=event)
    with pytest.raises(MapCancelled):
        regional.visible_index(index, (-71, 39, -69, 41), cancel=event)
    with pytest.raises(MapCancelled):
        regional.viewport_index(index, Viewport(40, -70, 16, 800, 400), cancel=event)


def test_symlink_index_and_source_rejected(tmp_path):
    index = build(tmp_path)
    link = tmp_path / 'link.ffmap'
    try:
        link.symlink_to(index.path)
    except OSError:
        pytest.skip('Symlinks unavailable')
    with pytest.raises(ValueError, match='regular'):
        regional.inspect_index(link)
    source_link = tmp_path / 'link.pbf'
    source_link.symlink_to(tmp_path / 'source.osm.pbf')
    with pytest.raises(ValueError, match='regular'):
        regional.prepare_index(source_link, tmp_path / 'new.ffmap')


def test_stream_receipt_only_after_complete_iteration(tmp_path):
    source = tmp_path / 'source.pbf'
    source.write_bytes(fixture())
    stream = PBFStream(source)
    iterator = iter(stream)
    next(iterator)
    assert stream.receipt is None
    list(iterator)
    assert stream.receipt['source_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_no_network_used(tmp_path, monkeypatch):
    import socket
    def denied(*_a, **_k):
        pytest.fail('Regional index attempted network use')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    index = build(tmp_path)
    index = regional.inspect_index(index.path)
    assert regional.search_index(index, 'street').features
    assert regional.visible_index(index, (-180, -85, 180, 85)).features


def test_cli_operates_offline_with_no_database_initialization(tmp_path, capsys):
    index = build(tmp_path)
    assert regional.main(['inspect', str(index.path)]) == 0
    assert 'visual-search-only' in capsys.readouterr().out
    assert regional.main(['search', str(index.path), 'Map Street']) == 0
    assert 'way/10' in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        regional.main(['inspect', str(tmp_path / 'missing.ffmap')])
    assert exc.value.code == 2


@pytest.mark.parametrize('value', ['{}', '{', '[]', '{"format":"bad"}'])
def test_malformed_receipt_produces_clear_error(tmp_path, value):
    index = build(tmp_path)
    index = change(index, 'UPDATE metadata SET value=?', (value,))
    with pytest.raises(ValueError):
        regional.inspect_index(index.path)


def test_geometry_query_budget_reports_truncation(tmp_path, monkeypatch):
    index = build(tmp_path)
    monkeypatch.setattr(regional, 'MAX_QUERY_POINTS', 1)
    found = regional.search_index(index, '')
    assert len(found.features) == 1 and found.limited
    assert found.features[0].id.startswith('node/')


def test_query_checks_post_query_sidecar(tmp_path):
    index = build(tmp_path)
    with pytest.raises(ValueError, match='changed during'):
        with regional._connect(index.path) as con:
            assert con.execute('SELECT COUNT(*) FROM features').fetchone()[0] == 2
            Path(str(index.path) + '-wal').write_bytes(b'changed during query')
