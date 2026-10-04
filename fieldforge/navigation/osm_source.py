"""Bounded, read-only preview of small OSM PBF snapshots; NOT a routing graph.

Decodes raw/zlib blobs, ordinary/dense nodes, ways and relation counts using
Python's standard library. Never downloads, executes files, joins missing nodes,
assembles relation geometry or infers that a road is open or traversable.
"""
from __future__ import annotations

import hashlib
import math
import struct
import unicodedata
import zlib
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable

from fieldforge.navigation.atlas import checked_bytes
from fieldforge.navigation.map_view import MAX_LATITUDE
from fieldforge.navigation.mbtiles import MapCancelled

MAX_FILE = 32 * 1024 * 1024
MAX_BLOB = 16 * 1024 * 1024
MAX_INFLATED = 128 * 1024 * 1024
MAX_NODES = 250000
MAX_WAYS = 60000
MAX_REFERENCES = 1000000
MAX_FEATURES = 25000
MAX_VALUES = 1000000
MAX_TAGS = 128
MAX_STRING = 16384
# Preserve policy-bearing fields for the opt-in local path model. Contact and
# contributor fields are still excluded. Values are not interpreted by this reader.
POLICY_BASES = frozenset(('access', 'vehicle', 'motor_vehicle', 'motorcar',
    'oneway', 'restriction', 'barrier', 'ford', 'impassable', 'construction',
    'proposed', 'disused', 'abandoned', 'maxheight', 'maxwidth', 'maxweight',
    'maxaxleload', 'maxlength', 'hazmat', 'opening_hours', 'date_on', 'date_off',
    'day_on', 'day_off', 'hour_on', 'hour_off', 'locked', 'except'))
NOTICE = 'Source preview only — NOT navigation. No routing graph, GPS, address matching or road-condition checks. Relations are counted, not drawn; access/oneway tags are descriptive, not enforced. Missing geometry is reported, never joined across gaps.'
KEEP_TAGS = frozenset(('name', 'name:en', 'ref', 'highway', 'waterway', 'water', 'natural', 'railway', 'building', 'landuse', 'leisure', 'amenity', 'place', 'man_made', 'aeroway', 'oneway', 'access', 'motor_vehicle', 'motorcar', 'foot', 'bicycle', 'surface', 'bridge', 'tunnel', 'layer', 'junction', 'maxspeed', 'area', 'service'))

# Public map address/name tags only. No contact, household or contributor fields.
LOCATION_TAGS = frozenset(('official_name', 'alt_name', 'short_name',
    'addr:housenumber', 'addr:housename', 'addr:street', 'addr:place', 'addr:city',
    'addr:postcode', 'addr:country', 'addr:state', 'addr:suburb', 'addr:unit',
    'addr:interpolation', 'entrance'))
KEEP_TAGS = KEEP_TAGS | LOCATION_TAGS

class SourcePreviewError(ValueError):
    """Malformed/unsupported input or an explicit preview budget was exceeded."""

def _fail(message):
    raise SourcePreviewError(message)

def _check(cancel):
    if cancel is not None and cancel.is_set():
        raise MapCancelled('Street-source read cancelled; previous preview is unchanged.')

def _varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            _fail('Truncated protobuf integer.')
        byte = data[offset]
        offset += 1
        if shift == 63 and byte > 1:
            _fail('Protobuf integer exceeds 64 bits.')
        value |= (byte & 127) << shift
        if byte < 128:
            return (value, offset)
    _fail('Invalid protobuf integer.')

def _fields(data):
    """Yield bounded wire fields as views; unknown fields never become commands."""
    pos = 0
    while pos < len(data):
        key, pos = _varint(data, pos)
        number, wire = (key >> 3, key & 7)
        if not 1 <= number < 1 << 29:
            _fail('Invalid protobuf field number.')
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire in (1, 2, 5):
            if wire == 2:
                size, pos = _varint(data, pos)
            else:
                size = 8 if wire == 1 else 4
            if size > len(data) - pos:
                _fail('Truncated protobuf field.')
            value = data[pos:pos + size]
            pos += size
        else:
            _fail('Unsupported protobuf wire type.')
        yield (number, wire, value)

def _message(data):
    result = {}
    count = 0
    for number, wire, value in _fields(data):
        count += 1
        if count > MAX_VALUES:
            _fail('Too many protobuf fields.')
        result.setdefault(number, []).append((wire, value))
    return result
_ABSENT = object()

def _one(message, number, wire, default=_ABSENT):
    fields = message.get(number, ())
    if not fields:
        if default is _ABSENT:
            _fail('Required OSM field is missing.')
        return default
    if len(fields) != 1 or fields[0][0] != wire:
        _fail('Duplicate or wrong-type OSM field.')
    return fields[0][1]

def _repeated(message, number, wire):
    for actual_wire, value in message.get(number, ()):
        if actual_wire != wire:
            _fail('Wrong-type repeated OSM field.')
        yield value

def _values(message, number):
    result = []
    for wire, raw in message.get(number, ()):
        if wire == 0:
            result.append(raw)
        elif wire == 2:
            pos = 0
            while pos < len(raw):
                value, pos = _varint(raw, pos)
                result.append(value)
                if len(result) > MAX_VALUES:
                    _fail('Too many packed OSM values.')
        else:
            _fail('Wrong-type packed OSM field.')
        if len(result) > MAX_VALUES:
            _fail('Too many packed OSM values.')
    return result

def _signed(value):
    return value - (1 << 64) if value & 1 << 63 else value

def _zigzag(value):
    return value >> 1 ^ -(value & 1)

def _delta(values):
    value = 0
    for raw in values:
        value += _zigzag(raw)
        if not -(1 << 63) <= value < 1 << 63:
            _fail('OSM delta overflow.')
        yield value

def _string(value):
    if len(value) > MAX_STRING:
        _fail('OSM string exceeds the preview limit.')
    try:
        return bytes(value).decode('utf-8')
    except UnicodeDecodeError as exc:
        raise SourcePreviewError('Invalid UTF-8 in OSM string table.') from exc

def _display(value):
    return ''.join((c if c.isprintable() else ' ' for c in value)).strip()[:500]

def _tags(keys, vals, strings):
    if len(keys) != len(vals) or len(keys) > MAX_TAGS:
        _fail('Invalid OSM tag arrays or too many tags.')
    found = {}
    seen = set()
    for key, val in zip(keys, vals):
        if not 0 <= key < len(strings) or not 0 <= val < len(strings) or key == 0:
            _fail('OSM tag refers to an invalid string.')
        name = strings[key]
        if name in seen:
            _fail('Duplicate OSM tag key.')
        seen.add(name)
        if name in KEEP_TAGS or name.split(':', 1)[0] in POLICY_BASES or name in ('type', 'except'):
            found[name] = _display(strings[val])
    return tuple(sorted(found.items()))

def _entity_tags(message, strings):
    return _tags(_values(message, 2), _values(message, 3), strings)

def _coord(lat, lon, granularity, lat_offset, lon_offset):
    lat = (lat_offset + granularity * lat) / 1000000000.0
    lon = (lon_offset + granularity * lon) / 1000000000.0
    if not math.isfinite(lat) or not math.isfinite(lon) or (not -90 <= lat <= 90) or (not -180 <= lon <= 180):
        _fail('OSM node has invalid WGS84 coordinates.')
    return (lon, lat)

def _inflate(raw):
    message = _message(raw)
    kinds = [key for key in (1, 3, 4, 5, 6, 7) if key in message]
    if len(kinds) != 1 or kinds[0] not in (1, 3):
        _fail('This preview supports one raw or zlib payload per OSM blob.')
    payload = _one(message, kinds[0], 2)
    if kinds[0] == 1:
        if len(payload) > MAX_BLOB:
            _fail('Uncompressed OSM blob exceeds the preview limit.')
        declared = _one(message, 2, 0, len(payload))
        if declared != len(payload):
            _fail('OSM raw-size declaration does not match.')
        return payload
    size = _one(message, 2, 0)
    if not 0 < size <= MAX_BLOB:
        _fail('Inflated OSM blob exceeds the preview limit.')
    inflater = zlib.decompressobj()
    try:
        data = inflater.decompress(payload, size + 1)
    except zlib.error as exc:
        raise SourcePreviewError('Invalid compressed OSM blob.') from exc
    if len(data) != size or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
        _fail('Compressed OSM blob is truncated, oversized or has trailing data.')
    return memoryview(data)

@dataclass(frozen=True)
class StreetFeature:
    id: str
    name: str
    kind: str
    geometry: tuple[tuple[float, float], ...]
    tags: tuple[tuple[str, str], ...]

@dataclass(frozen=True)
class TopologyNode:
    id: int
    coordinate: tuple[float, float]
    tags: tuple[tuple[str, str], ...]

@dataclass(frozen=True)
class TopologyWay:
    id: int
    refs: tuple[int, ...]
    tags: tuple[tuple[str, str], ...]

@dataclass(frozen=True)
class TopologyRelation:
    id: int
    tags: tuple[tuple[str, str], ...]
    # (role, OSM member type: node=0 / way=1 / relation=2, ID)
    members: tuple[tuple[str, int, int], ...]

@dataclass(frozen=True)
class SourceTopology:
    nodes: tuple[TopologyNode, ...]
    ways: tuple[TopologyWay, ...]
    relations: tuple[TopologyRelation, ...]

@dataclass(frozen=True)
class StreetSource:
    source_name: str
    sha256: str
    bytes: int
    nodes: int
    ways: int
    relations: int
    restrictions: int
    omitted_ways: int
    missing_node_ways: int
    polar_features: int
    replication_timestamp: int | None
    features: tuple[StreetFeature, ...]
    notice: str = NOTICE
    topology: SourceTopology | None = None

def _kind(tags):
    lookup = dict(tags)
    for key in ('highway', 'waterway', 'railway', 'building', 'natural', 'landuse', 'leisure', 'amenity', 'place', 'aeroway', 'man_made'):
        if lookup.get(key):
            return key + '=' + lookup[key]
    if any(lookup.get(key) for key in ('addr:housenumber', 'addr:housename',
                                      'addr:street', 'addr:place')):
        return 'address tags'
    return 'named feature' if any(lookup.get(key) for key in
        ('name', 'name:en', 'official_name', 'alt_name', 'short_name')) else ''

def _feature(kind, ident, coords, tags):
    lookup = dict(tags)
    address = ' '.join(v for v in (lookup.get('addr:housenumber'),
                                      lookup.get('addr:street') or lookup.get('addr:place')) if v)
    name = (lookup.get('name') or lookup.get('name:en') or lookup.get('official_name')
            or lookup.get('addr:housename') or address or lookup.get('ref') or ident)
    return StreetFeature(ident, name, kind, tuple(coords), tags)

def read_street_source(path: str | Path, *, cancel: Event | None=None, progress: Callable[[int, int], None] | None=None) -> StreetSource:
    """Parse a small local snapshot. No preview is returned on invalid/oversized input.

    Limits are operating bounds, not an audited hostile-file sandbox. Source
    snapshot metadata is self-reported. Unknown snapshot date stays unknown.
    """
    path = Path(path)
    raw = checked_bytes(path, MAX_FILE, cancel=cancel)
    return parse_street_source(raw, source_name=path.name, cancel=cancel, progress=progress)

def parse_street_source(raw: bytes, *, source_name='Local OSM PBF', cancel=None, progress=None, include_topology=False):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_FILE:
        _fail('Choose a nonempty OSM PBF extract no larger than 32 MiB.')
    _check(cancel)
    data = memoryview(raw)
    pos, inflated, block_count, reference_count = (0, 0, 0, 0)
    nodes, ways, relation_ids = ({}, {}, set())
    restrictions, timestamp = (0, None)
    topology_relations = []
    have_header = False
    have_data = False
    while pos < len(data):
        _check(cancel)
        if len(data) - pos < 4:
            _fail('Truncated OSM block length.')
        header_size = struct.unpack_from('>I', data, pos)[0]
        pos += 4
        if not 1 <= header_size <= 65535 or pos + header_size > len(data):
            _fail('Invalid OSM block header length.')
        header = _message(data[pos:pos + header_size])
        pos += header_size
        kind = bytes(_one(header, 1, 2))
        size = _one(header, 3, 0)
        if not 1 <= size <= MAX_BLOB or pos + size > len(data):
            _fail('Invalid or truncated OSM block payload.')
        body = _inflate(data[pos:pos + size])
        pos += size
        inflated += len(body)
        block_count += 1
        if inflated > MAX_INFLATED or block_count > 10000:
            _fail('OSM source exceeds the total preview decoding budget.')
        message = _message(body)
        if kind == b'OSMHeader':
            if have_header or have_data:
                _fail('OSM snapshot must have exactly one initial header.')
            required = {_string(value) for value in _repeated(message, 4, 2)}
            if 'OsmSchema-V0.6' not in required or required - {'OsmSchema-V0.6', 'DenseNodes'}:
                _fail('Unsupported OSM required feature; history/diff files cannot be previewed.')
            have_header = True
            timestamp = _one(message, 32, 0, None)
            if timestamp is not None and (not 0 <= timestamp <= 253402300799):
                _fail('Invalid replication timestamp.')
        elif kind == b'OSMData':
            if not have_header:
                _fail('OSM data appears before its snapshot header.')
            have_data = True
            strings = [_string(value) for value in _repeated(_message(_one(message, 1, 2)), 1, 2)]
            if not strings or strings[0] != '' or len(strings) > MAX_VALUES:
                _fail('Invalid OSM string table.')
            granularity = _one(message, 17, 0, 100)
            if not 1 <= granularity <= 1000000000:
                _fail('Invalid OSM coordinate granularity.')
            lat_offset = _signed(_one(message, 19, 0, 0))
            lon_offset = _signed(_one(message, 20, 0, 0))

            def add_node(ident, lat, lon, tags):
                if ident <= 0 or ident in nodes or len(nodes) >= MAX_NODES:
                    _fail('Duplicate/invalid node or too many nodes for a small-source preview.')
                nodes[ident] = (_coord(lat, lon, granularity, lat_offset, lon_offset), tags)
            for group_raw in _repeated(message, 2, 2):
                _check(cancel)
                group = _message(group_raw)
                if 5 in group:
                    _fail('Changesets are not supported in snapshot previews.')
                for node_raw in _repeated(group, 1, 2):
                    _check(cancel)
                    node = _message(node_raw)
                    add_node(_zigzag(_one(node, 1, 0)), _zigzag(_one(node, 8, 0)), _zigzag(_one(node, 9, 0)), _entity_tags(node, strings))
                dense_fields = group.get(2, ())
                if len(dense_fields) > 1:
                    _fail('Duplicate dense-node message.')
                for dense_raw in _repeated(group, 2, 2):
                    dense = _message(dense_raw)
                    ids, lats, lons = (_values(dense, number) for number in (1, 8, 9))
                    if len(ids) != len(lats) or len(ids) != len(lons) or len(nodes) + len(ids) > MAX_NODES:
                        _fail('Dense node arrays differ in length or exceed the preview budget.')
                    kv = _values(dense, 10)
                    cursor = 0
                    for index, (ident, lat, lon) in enumerate(zip(_delta(ids), _delta(lats), _delta(lons))):
                        if index % 256 == 0:
                            _check(cancel)
                        keys, vals = ([], [])
                        if kv:
                            while cursor < len(kv) and kv[cursor] != 0:
                                if cursor + 1 >= len(kv):
                                    _fail('Truncated dense node tags.')
                                keys.append(kv[cursor])
                                vals.append(kv[cursor + 1])
                                cursor += 2
                                if len(keys) > MAX_TAGS:
                                    _fail('Too many dense node tags.')
                            if cursor == len(kv):
                                _fail('Dense node tags lack their terminator.')
                            cursor += 1
                        add_node(ident, lat, lon, _tags(keys, vals, strings))
                    if cursor != len(kv):
                        _fail('Trailing dense node tags.')
                for way_raw in _repeated(group, 3, 2):
                    _check(cancel)
                    way = _message(way_raw)
                    ident = _signed(_one(way, 1, 0))
                    if ident <= 0 or ident in ways or len(ways) >= MAX_WAYS:
                        _fail('Duplicate/invalid way or too many ways for a small-source preview.')
                    refs = tuple(_delta(_values(way, 8)))
                    reference_count += len(refs)
                    if any((ref <= 0 for ref in refs)) or reference_count > MAX_REFERENCES:
                        _fail('Invalid way reference or too many node references.')
                    if 9 in way or 10 in way:
                        _fail('LocationsOnWays encoding is not supported by this preview.')
                    ways[ident] = (refs, _entity_tags(way, strings))
                for relation_raw in _repeated(group, 4, 2):
                    _check(cancel)
                    relation = _message(relation_raw)
                    ident = _signed(_one(relation, 1, 0))
                    if ident <= 0 or ident in relation_ids or len(relation_ids) >= MAX_WAYS:
                        _fail('Duplicate/invalid relation or too many relations.')
                    relation_ids.add(ident)
                    keys, vals = (_values(relation, 2), _values(relation, 3))
                    _tags(keys, vals, strings)
                    is_restriction = any(
                        (strings[k] == 'type' and strings[v].startswith('restriction'))
                        or strings[k].split(':', 1)[0] == 'restriction'
                        for k, v in zip(keys, vals))
                    restrictions += is_restriction
                    roles, members, types = (_values(relation, number) for number in (8, 9, 10))
                    if not len(roles) == len(members) == len(types):
                        _fail('Invalid relation member arrays.')
                    reference_count += len(members)
                    if reference_count > MAX_REFERENCES or any((r >= len(strings) for r in roles)) or any((t > 2 for t in types)) or any((i <= 0 for i in _delta(members))):
                        _fail('Invalid relation members or too many references.')
                    if include_topology and is_restriction:
                        topology_relations.append(TopologyRelation(ident,
                            _entity_tags(relation, strings), tuple(
                                (strings[r], t, i) for r, t, i in
                                zip(roles, types, _delta(members)))))
        else:
            _fail('Unsupported OSM block type.')
        if progress:
            progress(pos, len(data))
    if not have_header or not have_data:
        _fail('OSM snapshot lacks a header or data block.')
    features, missing, omitted, polar = ([], 0, 0, 0)
    for ident, (refs, tags) in ways.items():
        _check(cancel)
        feature_kind = _kind(tags)
        if not feature_kind or len(refs) < 2:
            omitted += 1
            continue
        if any((ref not in nodes for ref in refs)):
            missing += 1
            continue
        coords = tuple((nodes[ref][0] for ref in refs))
        if any((abs(lat) > MAX_LATITUDE for _lon, lat in coords)):
            polar += 1
            continue
        features.append(_feature(feature_kind, f'way/{ident}', coords, tags))
        if len(features) > MAX_FEATURES:
            _fail('Too many display features; use a smaller extract.')
    for ident, (coords, tags) in nodes.items():
        _check(cancel)
        feature_kind = _kind(tags)
        if feature_kind:
            if abs(coords[1]) > MAX_LATITUDE:
                polar += 1
                continue
            features.append(_feature(feature_kind, f'node/{ident}', (coords,), tags))
            if len(features) > MAX_FEATURES:
                _fail('Too many display features; use a smaller extract.')
    _check(cancel)
    topology = None
    if include_topology:
        topology = SourceTopology(
            tuple(TopologyNode(i, coord, tags) for i, (coord, tags) in nodes.items()),
            tuple(TopologyWay(i, refs, tags) for i, (refs, tags) in ways.items()),
            tuple(topology_relations))
    return StreetSource(_display(str(source_name)), hashlib.sha256(raw).hexdigest(), len(raw), len(nodes), len(ways), len(relation_ids), restrictions, omitted, missing, polar, timestamp, tuple(features), topology=topology)

def search_features(source: StreetSource, query: str, limit=100):
    if not isinstance(query, str) or len(query) > 200 or type(limit) is not int or (not 1 <= limit <= 500):
        _fail('Search accepts at most 200 characters and 1–500 results.')

    def fold(value):
        return ''.join((c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c)))
    terms = fold(query).split()
    matches = []
    total = 0
    for feature in source.features:
        haystack = fold(feature.name + ' ' + feature.kind + ' ' + feature.id)
        if all((term in haystack for term in terms)):
            total += 1
            if len(matches) < limit:
                matches.append(feature)
    return (tuple(matches), total)

def main(argv=None):
    """Read-only command-line inspection; never writes or starts a server."""
    import argparse
    import json
    from collections import Counter
    parser = argparse.ArgumentParser(description='Inspect a small OSM PBF locally; not a route graph.')
    parser.add_argument('source', type=Path)
    args = parser.parse_args(argv)
    try:
        source = read_street_source(args.source)
    except (OSError, ValueError) as exc:
        parser.exit(2, str(exc) + '\n')
    summary = {k: v for k, v in vars(source).items() if k != 'features'}
    summary['preview_features'] = len(source.features)
    summary['feature_types'] = dict(Counter((feature.kind for feature in source.features)))
    print(json.dumps(summary, ensure_ascii=False, allow_nan=False, indent=2))
if __name__ == '__main__':
    main()
