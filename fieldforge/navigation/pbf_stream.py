"""Sequential PBF entities for the disk-backed index, with bounded fileblocks.

The small-source reader remains unchanged. Both readers use the same strict
wire/coordinate/tag primitives; this one never builds an all-nodes dictionary.
Contributor/contact metadata is not emitted. Only snapshot raw/zlib is supported.
"""
from __future__ import annotations

import hashlib
import os
import stat
import struct
from dataclasses import dataclass
from pathlib import Path

from fieldforge.navigation import osm_source as wire


@dataclass(frozen=True)
class IndexLimits:
    """Operating ceilings, not assertions of country-size performance."""

    file_bytes: int = 2 * 1024**3
    inflated_bytes: int = 16 * 1024**3
    blocks: int = 100000
    nodes: int = 20000000
    ways: int = 2000000
    relations: int = 1000000
    references: int = 50000000
    way_points: int = 10000
    features: int = 2000000
    database_bytes: int = 4 * 1024**3  # each of output and temporary node store

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in self.__dict__.values()):
            raise ValueError('Index limits must be positive integers.')


def signature(path: Path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Choose a regular local file, not a link or device.')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def checked_open(path: Path):
    before = signature(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
                         | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0))
    try:
        actual = os.fstat(descriptor)
        key = (actual.st_dev, actual.st_ino, actual.st_size,
               actual.st_mtime_ns, actual.st_ctime_ns)
        if not stat.S_ISREG(actual.st_mode) or key != before:
            raise ValueError('Local source changed while opening.')
        return os.fdopen(descriptor, 'rb'), before
    except BaseException:
        os.close(descriptor)
        raise


class PBFStream:
    """One-pass event iterator. Receipt is populated only after successful EOF."""

    def __init__(self, path, *, limits=None, cancel=None, progress=None, include_restrictions=False):
        self.path = Path(path)
        self.include_restrictions = include_restrictions
        self.limits = limits or IndexLimits()
        self.cancel = cancel
        self.progress = progress
        self.receipt = None
        self.counts = dict(nodes=0, ways=0, relations=0, references=0, restrictions=0)
        self.timestamp = None

    def _count(self, key, amount=1):
        self.counts[key] += amount
        ceiling = getattr(self.limits, key, None)
        if ceiling is not None and self.counts[key] > ceiling:
            raise ValueError(f'Regional index {key} budget exceeded; use a smaller extract.')

    def __iter__(self):
        f, before = checked_open(self.path)
        digest = hashlib.sha256()
        processed = inflated = blocks = 0
        have_header = have_data = False
        self.receipt = None
        with f:
            if not 1 <= before[2] <= self.limits.file_bytes:
                raise ValueError('Source is empty or exceeds the regional input budget.')

            def take(size):
                nonlocal processed
                wire._check(self.cancel)
                raw = f.read(size)
                processed += len(raw)
                digest.update(raw)
                if len(raw) != size:
                    raise ValueError('Truncated OSM fileblock.')
                if processed > self.limits.file_bytes:
                    raise ValueError('Source exceeds the regional input budget.')
                return memoryview(raw)

            while processed < before[2]:
                n = struct.unpack('>I', take(4))[0]
                if not 1 <= n <= 65535:
                    raise ValueError('Invalid OSM block header length.')
                header = wire._message(take(n))
                kind = bytes(wire._one(header, 1, 2))
                size = wire._one(header, 3, 0)
                if not 1 <= size <= wire.MAX_BLOB:
                    raise ValueError('OSM fileblock exceeds the per-block budget.')
                body = wire._inflate(take(size))
                inflated += len(body)
                blocks += 1
                if inflated > self.limits.inflated_bytes or blocks > self.limits.blocks:
                    raise ValueError('Regional PBF decoding budget exceeded.')
                message = wire._message(body)
                if kind == b'OSMHeader':
                    if have_header or have_data:
                        raise ValueError('OSM snapshot requires one initial header.')
                    required = {wire._string(v) for v in wire._repeated(message, 4, 2)}
                    if 'OsmSchema-V0.6' not in required or required - {'OsmSchema-V0.6', 'DenseNodes'}:
                        raise ValueError('Unsupported required feature; use a snapshot, not history.')
                    self.timestamp = wire._one(message, 32, 0, None)
                    if self.timestamp is not None and not 0 <= self.timestamp <= 253402300799:
                        raise ValueError('Invalid replication timestamp.')
                    have_header = True
                elif kind == b'OSMData':
                    if not have_header:
                        raise ValueError('OSM data before its header.')
                    have_data = True
                    yield from self._primitive(message)
                else:
                    raise ValueError('Unsupported OSM fileblock type.')
                if self.progress:
                    # The first 70% is input decoding; the caller assembles geometry next.
                    self.progress(processed * 70 // before[2], 100)
            wire._check(self.cancel)
            if not have_header or not have_data:
                raise ValueError('OSM snapshot needs header and data blocks.')
            if f.read(1) or signature(self.path) != before:
                raise ValueError('Local source changed while preparing the regional index.')
        self.receipt = dict(source_name=wire._display(self.path.name),
                            source_sha256=digest.hexdigest(), source_bytes=processed,
                            replication_timestamp=self.timestamp, **self.counts)

    def _primitive(self, message):
        strings = [wire._string(v) for v in wire._repeated(
            wire._message(wire._one(message, 1, 2)), 1, 2)]
        if not strings or strings[0] or len(strings) > wire.MAX_VALUES:
            raise ValueError('Invalid OSM string table.')
        gran = wire._one(message, 17, 0, 100)
        if not 1 <= gran <= 1000000000:
            raise ValueError('Invalid OSM granularity.')
        lat_offset = wire._signed(wire._one(message, 19, 0, 0))
        lon_offset = wire._signed(wire._one(message, 20, 0, 0))

        def node(ident, lat, lon, tags):
            if not 0 < ident < 1 << 63:
                raise ValueError('Invalid OSM node ID.')
            self._count('nodes')
            return ('node', ident, wire._coord(lat, lon, gran, lat_offset, lon_offset), tags)

        for raw in wire._repeated(message, 2, 2):
            wire._check(self.cancel)
            group = wire._message(raw)
            if 5 in group:
                raise ValueError('Changesets cannot be prepared as a snapshot.')
            for raw_node in wire._repeated(group, 1, 2):
                wire._check(self.cancel)
                item = wire._message(raw_node)
                yield node(wire._zigzag(wire._one(item, 1, 0)),
                           wire._zigzag(wire._one(item, 8, 0)),
                           wire._zigzag(wire._one(item, 9, 0)),
                           wire._entity_tags(item, strings))
            if len(group.get(2, ())) > 1:
                raise ValueError('Duplicate dense node message.')
            for dense_raw in wire._repeated(group, 2, 2):
                dense = wire._message(dense_raw)
                ids, lats, lons = (wire._values(dense, n) for n in (1, 8, 9))
                if not len(ids) == len(lats) == len(lons):
                    raise ValueError('Dense node arrays differ in length.')
                kv, cursor = wire._values(dense, 10), 0
                for index, (ident, lat, lon) in enumerate(zip(
                        wire._delta(ids), wire._delta(lats), wire._delta(lons))):
                    if index % 256 == 0:
                        wire._check(self.cancel)
                    keys, values = [], []
                    if kv:
                        while cursor < len(kv) and kv[cursor] != 0:
                            if cursor + 1 >= len(kv):
                                raise ValueError('Truncated dense tags.')
                            keys.append(kv[cursor])
                            values.append(kv[cursor + 1])
                            cursor += 2
                            if len(keys) > wire.MAX_TAGS:
                                raise ValueError('Too many node tags.')
                        if cursor == len(kv):
                            raise ValueError('Dense tags lack terminator.')
                        cursor += 1
                    yield node(ident, lat, lon, wire._tags(keys, values, strings))
                if cursor != len(kv):
                    raise ValueError('Trailing dense tags.')
            for way_raw in wire._repeated(group, 3, 2):
                wire._check(self.cancel)
                item = wire._message(way_raw)
                ident = wire._signed(wire._one(item, 1, 0))
                if ident <= 0 or 9 in item or 10 in item:
                    raise ValueError('Invalid way ID or unsupported LocationsOnWays.')
                refs = tuple(wire._delta(wire._values(item, 8)))
                if len(refs) > self.limits.way_points or any(r <= 0 for r in refs):
                    raise ValueError('Invalid or over-budget way references.')
                self._count('ways')
                self._count('references', len(refs))
                yield ('way', ident, refs, wire._entity_tags(item, strings))
            for relation_raw in wire._repeated(group, 4, 2):
                wire._check(self.cancel)
                item = wire._message(relation_raw)
                ident = wire._signed(wire._one(item, 1, 0))
                if ident <= 0:
                    raise ValueError('Invalid relation ID.')
                tags = wire._entity_tags(item, strings)
                roles, refs, types = (wire._values(item, n) for n in (8, 9, 10))
                if (not len(roles) == len(refs) == len(types)
                        or any(r >= len(strings) for r in roles)
                        or any(t > 2 for t in types)
                        or any(r <= 0 for r in wire._delta(refs))):
                    raise ValueError('Invalid relation member arrays.')
                self._count('relations')
                self._count('references', len(refs))
                lookup = dict(tags)
                is_restriction = lookup.get('type', '').startswith('restriction') or any(
                        k.split(':', 1)[0] == 'restriction' for k in lookup)
                if is_restriction:
                    self._count('restrictions')
                # Visual indexes retain only IDs/counts. Route preparation opts in to
                # every policy-bearing restriction, including unsupported ones so the
                # builder can refuse rather than silently dropping them.
                if self.include_restrictions and is_restriction:
                    members = tuple((strings[r], t, n) for r, t, n in
                                    zip(roles, types, wire._delta(refs)))
                    yield ('restriction', ident, members, tags)
                else:
                    yield ('relation', ident, (), ())
