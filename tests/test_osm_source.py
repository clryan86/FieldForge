"""PBF reader checks, independent fixture encoder, and real historical OSM bytes."""
from __future__ import annotations

import hashlib
import struct
import threading
import zlib
from pathlib import Path

import pytest

from fieldforge.navigation import osm_source as osm
from fieldforge.navigation.mbtiles import MapCancelled

SAMPLE = Path(__file__).resolve().parents[1] / 'examples/street-source/historic-sample.osm.pbf'

def vi(n):
    n &= (1 << 64) - 1
    out = bytearray()
    while n > 127:
        out.append(n & 127 | 128)
        n >>= 7
    return bytes(out) + bytes((n,))

def zz(n):
    return n << 1 ^ n >> 63

def integer(k, n):
    return vi(k << 3) + vi(n)

def binary(k, value):
    return vi(k << 3 | 2) + vi(len(value)) + value

def packed(k, values):
    return binary(k, b''.join((vi(x) for x in values)))

def block(kind, data, compressed=True):
    blob = integer(2, len(data)) + binary(3, zlib.compress(data)) if compressed else binary(1, data)
    header = binary(1, kind) + integer(3, len(blob))
    return struct.pack('>I', len(header)) + header + blob

def header(extra=b'', required=('OsmSchema-V0.6', 'DenseNodes')):
    return block(b'OSMHeader', b''.join((binary(4, name.encode()) for name in required)) + extra)

def node(ident, lon, lat, tags=b''):
    return integer(1, zz(ident)) + integer(8, zz(round(lat * 10000000.0))) + integer(9, zz(round(lon * 10000000.0))) + tags

def way(ident=10, refs=(1, 2), keys=(1, 3), vals=(2, 4), extra=b''):
    previous = 0
    deltas = []
    for value in refs:
        deltas.append(zz(value - previous))
        previous = value
    return integer(1, ident) + packed(2, keys) + packed(3, vals) + packed(8, deltas) + extra

def primitive(group, strings=('', 'highway', 'residential', 'name', 'Map Street'), extra=b''):
    table = b''.join((binary(1, s.encode()) for s in strings))
    return block(b'OSMData', binary(1, table) + binary(2, group) + extra)

def fixture(dense=False, missing=False, extra_header=b'', **kwargs):
    tags = packed(2, (3,)) + packed(3, (4,))
    if dense:
        raw = packed(1, (zz(1), zz(1))) + packed(8, (zz(400000000), zz(10000))) + packed(9, (zz(-700000000), zz(10000))) + packed(10, (3, 4, 0, 0))
        group = binary(2, raw)
    else:
        group = binary(1, node(1, -70, 40, tags)) + binary(1, node(2, -69.999, 40.001))
    group += binary(3, way(refs=(1, 99) if missing else (1, 2), **kwargs))
    return header(extra_header) + primitive(group)

def test_raw_and_zlib_framing():
    a = block(b'OSMHeader', binary(4, b'OsmSchema-V0.6'), False)
    a += primitive(binary(1, node(1, 5, 20)))
    result = osm.parse_street_source(a)
    assert result.nodes == 1 and result.features == ()

@pytest.mark.parametrize('dense', (False, True))
def test_decodes_exact_geometry_and_tags(dense):
    result = osm.parse_street_source(fixture(dense=dense))
    road = next((f for f in result.features if f.id == 'way/10'))
    assert road.geometry == ((-70.0, 40.0), (-69.999, 40.001))
    assert road.name == 'Map Street' and road.kind == 'highway=residential'
    assert result.nodes == 2 and result.ways == 1 and (result.replication_timestamp is None)

def test_negative_offsets_and_granularity():
    group = binary(1, integer(1, zz(1)) + integer(8, zz(5)) + integer(9, zz(-7)) + packed(2, [3]) + packed(3, [4]))
    raw = header() + primitive(group, extra=integer(17, 1000) + integer(19, -1000000000) + integer(20, 2000000000))
    feature = osm.parse_street_source(raw).features[0]
    assert feature.geometry == ((1.999993, -0.999995),)

def test_input_not_order_dependent_and_missing_nodes_never_joined():
    raw = header() + primitive(binary(3, way())) + primitive(binary(1, node(2, 1, 2)) + binary(1, node(1, 3, 4)))
    assert osm.parse_street_source(raw).features[0].geometry == ((3.0, 4.0), (1.0, 2.0))
    result = osm.parse_street_source(fixture(missing=True))
    assert result.missing_node_ways == 1 and all((not f.id.startswith('way/') for f in result.features))

def test_history_and_unknown_required_features_refused():
    for feature in ('HistoricalInformation', 'UnknownFeature', 'LocationsOnWays'):
        with pytest.raises(osm.SourcePreviewError, match='required feature'):
            osm.parse_street_source(header(required=('OsmSchema-V0.6', feature)) + primitive(b''))

def test_relations_counted_but_not_routed_or_rendered():
    strings = ('', 'type', 'restriction', 'from', 'to', 'via')
    relation = integer(1, 50) + packed(2, [1]) + packed(3, [2]) + packed(8, [3, 4, 5]) + packed(9, [zz(10), zz(1), zz(-10)]) + packed(10, [1, 1, 0])
    result = osm.parse_street_source(header() + primitive(binary(4, relation), strings))
    assert result.relations == 1 and result.restrictions == 1 and (not result.features)
    assert 'NOT navigation' in result.notice

def test_no_contributor_or_contact_metadata_in_model():
    strings = ('', 'name', 'Public Place', 'email', 'private@example.invalid', 'phone', '555-sensitive')
    n = node(1, 0, 0, packed(2, [1, 3, 5]) + packed(3, [2, 4, 6]) + binary(4, b'contributor_id_never_decoded'))
    result = osm.parse_street_source(header() + primitive(binary(1, n), strings))
    assert result.features[0].tags == (('name', 'Public Place'),)
    assert 'private@' not in repr(result) and '555-sensitive' not in repr(result)

def test_replication_time_is_optional_and_not_acquisition_time():
    result = osm.parse_street_source(fixture(extra_header=integer(32, 1000000)))
    assert result.replication_timestamp == 1000000
    with pytest.raises(ValueError, match='timestamp'):
        osm.parse_street_source(fixture(extra_header=integer(32, (1 << 64) - 1)))

def test_source_hash_exact_and_display_name_sanitized(tmp_path):
    data = fixture()
    p = tmp_path / 'test.osm.pbf'
    p.write_bytes(data)
    result = osm.read_street_source(p)
    assert result.sha256 == hashlib.sha256(data).hexdigest() and result.bytes == len(data)
    assert osm.parse_street_source(data, source_name='\x00name\n').source_name == 'name'

def test_cancel_before_and_during_decode():
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(MapCancelled):
        osm.parse_street_source(fixture(), cancel=cancel)
    cancel.clear()
    with pytest.raises(MapCancelled):
        osm.parse_street_source(fixture(), cancel=cancel, progress=lambda *_: cancel.set())

def test_progress_monotonic():
    events = []
    data = fixture()
    osm.parse_street_source(data, progress=lambda n, total: events.append((n, total)))
    assert events[-1] == (len(data), len(data)) and events == sorted(events)

def test_real_public_sample_matches_published_identity_and_geometry():
    raw = SAMPLE.read_bytes()
    assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\x00' + raw).hexdigest() == '8a22edfee9bf1514af8cecf183e0e994bc40041d'
    result = osm.read_street_source(SAMPLE)
    assert (result.nodes, result.ways, result.relations) == (290, 44, 5)
    assert result.missing_node_ways == 0 and result.restrictions == 0
    found, total = osm.search_features(result, 'Wellfield Road')
    assert total == 1 and found[0].id == 'way/3084923' and (len(found[0].geometry) == 19)
    assert all((-0.3 < x < -0.2 and 51.7 < y < 51.8 for x, y in found[0].geometry))
    assert result.replication_timestamp is None

def test_search_no_fabricated_matches_and_limit():
    result = osm.read_street_source(SAMPLE)
    assert osm.search_features(result, 'NOT A REAL MATCH') == ((), 0)
    rows, total = osm.search_features(result, '', 1)
    assert len(rows) == 1 and total == len(result.features)
    rows, total = osm.search_features(result, 'highway=residential')
    assert total > 1 and all((f.kind == 'highway=residential' for f in rows))

@pytest.mark.parametrize('query,limit', [(None, 1), ('x' * 201, 1), ('x', 0), ('x', True), ('x', 501)])
def test_search_validates_query(query, limit):
    with pytest.raises(ValueError):
        osm.search_features(osm.parse_street_source(fixture()), query, limit)

@pytest.mark.parametrize('data', [b'', b'hi', b'\x00' * 4, b'\x00\x01\x00\x00', b'\xff' * 20])
def test_invalid_framing(data):
    with pytest.raises(ValueError):
        osm.parse_street_source(data)

def test_every_truncation_refused():
    data = fixture()
    for size in range(len(data)):
        with pytest.raises(ValueError):
            osm.parse_street_source(data[:size])

@pytest.mark.parametrize('change', ['bad_key', 'bad_value', 'unequal_tags', 'duplicate_tags', 'duplicate_node', 'duplicate_way', 'invalid_coord', 'bad_ref', 'wrong_wire', 'unknown_block', 'data_first', 'double_header', 'locations_on_ways', 'zero_granularity'])
def test_malformed_primitives(change):
    group = binary(1, node(1, 1, 1)) + binary(1, node(2, 2, 2))
    extra = b''
    start = header()
    end = b''
    if change == 'bad_key':
        group += binary(3, way(keys=[999], vals=[1]))
    elif change == 'bad_value':
        group += binary(3, way(keys=[1], vals=[999]))
    elif change == 'unequal_tags':
        group += binary(3, way(keys=[1], vals=[]))
    elif change == 'duplicate_tags':
        group += binary(3, way(keys=[1, 1], vals=[2, 2]))
    elif change == 'duplicate_node':
        group += binary(1, node(1, 2, 2))
    elif change == 'duplicate_way':
        group += binary(3, way()) * 2
    elif change == 'invalid_coord':
        group += binary(1, node(3, 300, 91))
    elif change == 'bad_ref':
        group += binary(3, way(refs=[0, 2]))
    elif change == 'wrong_wire':
        group += binary(3, binary(1, b'wrong'))
    elif change == 'unknown_block':
        end = block(b'Other', b'')
    elif change == 'data_first':
        start = b''
    elif change == 'double_header':
        start += header()
    elif change == 'locations_on_ways':
        group += binary(3, way(extra=packed(9, [1, 1])))
    elif change == 'zero_granularity':
        extra = integer(17, 0)
    with pytest.raises(ValueError):
        osm.parse_street_source(start + primitive(group, extra=extra) + end)

@pytest.mark.parametrize('key_values', ([3, 4], [3], [3, 4, 0, 1], [999, 4, 0], [3, 4, 0, 0]))
def test_dense_tags_validated(key_values):
    dense = packed(1, [zz(1)]) + packed(8, [zz(1)]) + packed(9, [zz(1)]) + packed(10, key_values)
    with pytest.raises(ValueError):
        osm.parse_street_source(header() + primitive(binary(2, dense)))

def test_dense_empty_tags_and_unpacked_values():
    dense = integer(1, zz(1)) + integer(8, zz(-1)) + integer(9, zz(2))
    result = osm.parse_street_source(header() + primitive(binary(2, dense)))
    assert result.nodes == 1 and (not result.features)

def test_dense_array_mismatch():
    dense = packed(1, [zz(1)]) + packed(8, [zz(1)]) + packed(9, [])
    with pytest.raises(ValueError):
        osm.parse_street_source(header() + primitive(binary(2, dense)))

@pytest.mark.parametrize('attribute,value', [('MAX_FILE', 2), ('MAX_BLOB', 2), ('MAX_INFLATED', 2), ('MAX_NODES', 1), ('MAX_WAYS', 0), ('MAX_REFERENCES', 1), ('MAX_FEATURES', 0), ('MAX_TAGS', 1), ('MAX_VALUES', 1)])
def test_each_budget_fails_without_partial_result(monkeypatch, attribute, value):
    monkeypatch.setattr(osm, attribute, value)
    with pytest.raises(ValueError):
        osm.parse_street_source(fixture())

def test_polar_features_omitted_explicitly():
    result = osm.parse_street_source(header() + primitive(binary(1, node(1, 1, 89, packed(2, [3]) + packed(3, [4])))))
    assert result.polar_features == 1 and (not result.features)

def test_unsupported_compression_and_corrupt_zlib():
    for blob in (integer(2, 4) + binary(4, b'lzma'), integer(2, 1) + binary(3, zlib.compress(b'abcdefghij')), integer(2, 3) + binary(3, b'abc'), integer(2, 1) + binary(3, zlib.compress(b'a') + b'extra')):
        bh = binary(1, b'OSMHeader') + integer(3, len(blob))
        with pytest.raises(ValueError):
            osm.parse_street_source(struct.pack('>I', len(bh)) + bh + blob)

def test_no_network_or_source_writes(monkeypatch, tmp_path):
    import socket
    monkeypatch.setattr(socket, 'socket', lambda *_a, **_k: pytest.fail('no network'))
    p = tmp_path / 'source.pbf'
    p.write_bytes(fixture())
    before = p.read_bytes()
    osm.read_street_source(p)
    assert p.read_bytes() == before and list(tmp_path.iterdir()) == [p]

def test_symlink_not_followed(tmp_path):
    p = tmp_path / 'real.pbf'
    p.write_bytes(fixture())
    link = tmp_path / 'link.pbf'
    try:
        link.symlink_to(p)
    except (OSError, NotImplementedError):
        pytest.skip('Symlinks unavailable')
    with pytest.raises(ValueError):
        osm.read_street_source(link)

def test_command_line_reads_real_source(capsys):
    import json
    osm.main([str(SAMPLE)])
    value = json.loads(capsys.readouterr().out)
    assert value['nodes'] == 290 and value['preview_features'] == 51

def test_command_line_failure_is_explicit(capsys, tmp_path):
    with pytest.raises(SystemExit) as error:
        osm.main([str(tmp_path / 'missing.pbf')])
    assert error.value.code == 2 and capsys.readouterr().err

def test_html_export_escapes_inert_names_and_no_contributor_fields():
    from dataclasses import replace

    from fieldforge.navigation.street_export import street_preview_html
    source = osm.parse_street_source(fixture())
    attack = '</script><img src=https://example.invalid/track onerror=alert(1)>'
    source = replace(source, source_name=attack, features=(replace(source.features[0], name=attack),))
    text = street_preview_html(source).decode()
    assert attack not in text and '\\u003c/script\\u003e' in text
    assert "default-src 'none'" in text and text.count('</script>') == 1
    assert 'geolocation' not in text and 'localStorage' not in text and ('fetch(' not in text)

def test_html_export_sample_labels_and_limit(monkeypatch):
    from fieldforge.navigation import street_export
    source = osm.read_street_source(SAMPLE)
    text = street_export.street_preview_html(source)
    assert b'HISTORICAL FORMAT SAMPLE' in text and b'Wellfield Road' in text
    monkeypatch.setattr(street_export, 'MAX_HTML', 10)
    with pytest.raises(ValueError):
        street_export.street_preview_html(source)
