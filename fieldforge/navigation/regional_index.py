"""Prepare/query read-only regional street indexes, without an all-region heap.

A .ffmap is a visual/search database, NOT a routing graph. New preparations retain
explicit address tags for bounded lookup; no interpolation or address inference.
Raw PBF and household data are untouched; only complete new outputs are published.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import stat
import struct
import tempfile
import time
import unicodedata
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fieldforge.navigation import osm_source as osm
from fieldforge.navigation.map_view import MAX_LATITUDE, Viewport, unproject
from fieldforge.navigation.mbtiles import MapCancelled
from fieldforge.navigation.pbf_stream import IndexLimits, PBFStream, checked_open, signature

APP_ID = 0x46464D31
VERSION = 1
MAX_QUERY_POINTS = 50000
MAX_QUERY_FEATURES = 1000
META_LIMIT = 32768
MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_ARCHIVE_INDEX_BYTES = 4 * 1024**3
NOTICE = ('Prepared source geometry, NOT driving directions. Relations and turn restrictions '
          'are counted, not applied or drawn. No GPS, address interpolation, closures, or safety '
          'checks. Blank space and a truncated view do not establish missing real-world roads.')
ATTRIBUTION = '© OpenStreetMap contributors • ODbL 1.0 • https://www.openstreetmap.org/copyright'
SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE features (
 fid INTEGER PRIMARY KEY, osm_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
 kind TEXT NOT NULL, geometry BLOB NOT NULL, tags TEXT NOT NULL,
 search TEXT NOT NULL, west REAL NOT NULL, east REAL NOT NULL,
 south REAL NOT NULL, north REAL NOT NULL);
CREATE VIRTUAL TABLE feature_bounds USING rtree(fid, west, east, south, north);
"""
FTS_SCHEMA = 'CREATE VIRTUAL TABLE feature_search USING fts5(search)'


@dataclass(frozen=True)
class PreparedIndex:
    path: Path
    fingerprint: tuple
    metadata: dict


@dataclass(frozen=True)
class IndexResults:
    features: tuple[osm.StreetFeature, ...]
    limited: bool


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _normalize(value):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', value).casefold()))


def _temp(parent, suffix):
    fd, name = tempfile.mkstemp(prefix='.fieldforge-index-', suffix=suffix, dir=parent)
    os.close(fd)
    return Path(name)


def _publish_index(temporary, target):
    """Publish a complete index atomically without replacing an existing path."""
    if os.name == 'nt':
        # Windows rename refuses an existing target and also works on volumes
        # without hard links. POSIX rename would replace a competing file.
        os.rename(temporary, target)
    else:
        os.link(temporary, target)
    temporary.unlink(missing_ok=True)  # Windows moved this private pathname.


def _new_db(path, limits):
    con = sqlite3.connect(path)
    con.execute('PRAGMA page_size=4096')
    con.execute('PRAGMA journal_mode=DELETE')
    con.execute('PRAGMA synchronous=FULL')
    con.execute('PRAGMA temp_store=FILE')
    con.execute('PRAGMA cache_size=-16384')
    con.execute('PRAGMA max_page_count=' + str(max(1, limits.database_bytes // 4096)))
    return con


def _coords_blob(coords):
    return b''.join(struct.pack('<dd', lon, lat) for lon, lat in coords)


def _remove_temporary(path):
    if path is not None:
        for suffix in ('', '-journal', '-wal', '-shm'):
            Path(str(path) + suffix).unlink(missing_ok=True)


def prepare_index(source, target, *, cancel=None, progress=None, limits=None,
                  expected_sha256=None, use_fts=True, origin=None):
    """Stream PBF to temporary disk tables, assemble indexed features, publish new file.

    Up to two database_bytes budgets plus SQLite temporary space can be required.
    No network; no replace option. Cancellation before publication removes temporary
    files. Cancellation racing after publication may leave a completed valid index.
    """
    limits = limits or IndexLimits()
    source, target = Path(source), Path(target)
    if target.suffix.casefold() != '.ffmap':
        raise ValueError('Use a new filename ending in .ffmap.')
    if target.exists() or target.is_symlink():
        raise FileExistsError('An output already exists; choose a new .ffmap filename.')
    if not target.parent.is_dir():
        raise ValueError('Choose an existing output folder.')
    if expected_sha256 is not None and not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('Invalid expected source checksum.')
    if origin is not None:
        if (not isinstance(origin, dict) or set(origin) != {'region', 'source_url', 'downloaded_utc'}
                or any(not isinstance(v, str) or len(v) > 1000 for v in origin.values())
                or not origin['source_url'].startswith('https://download.geofabrik.de/')):
            raise ValueError('Invalid publisher-source provenance.')
    osm._check(cancel)
    before = signature(source)
    if not 1 <= before[2] <= limits.file_bytes:
        raise ValueError('Source is empty or exceeds the regional input budget.')
    work = output = None
    spool = result = None
    try:
        work, output = _temp(target.parent, '.work.sqlite'), _temp(target.parent, '.part.sqlite')
        spool, result = _new_db(work, limits), _new_db(output, limits)
        if cancel is not None:
            spool.set_progress_handler(lambda: int(cancel.is_set()), 1000)
            result.set_progress_handler(lambda: int(cancel.is_set()), 1000)
        spool.executescript('''
            CREATE TABLE nodes (id INTEGER PRIMARY KEY, lon REAL, lat REAL, tags TEXT);
            CREATE TABLE ways (id INTEGER PRIMARY KEY, refs BLOB, tags TEXT);
            CREATE TABLE relations (id INTEGER PRIMARY KEY);
        ''')
        result.executescript(SCHEMA)
        result.execute('PRAGMA application_id=' + str(APP_ID))
        result.execute('PRAGMA user_version=' + str(VERSION))
        fts = False
        if use_fts:
            try:
                result.execute(FTS_SCHEMA)
                fts = True
            except sqlite3.OperationalError as exc:
                if 'no such module' not in str(exc):
                    raise
        counters = dict(features=0, omitted_ways=0, missing_node_ways=0,
                        polar_features=0, dateline_features=0, address_features=0)
        extent = None

        def emit(ident, coords, tags):
            nonlocal extent
            kind = osm._kind(tags)
            if not kind:
                return
            if any(abs(lat) > MAX_LATITUDE for _, lat in coords):
                counters['polar_features'] += 1
                return
            # Whole antimeridian-crossing ways are deliberately omitted until a
            # split-geometry index format is introduced. Never draw a false chord.
            if any(abs(a[0] - b[0]) > 180 for a, b in zip(coords, coords[1:])):
                counters['dateline_features'] += 1
                return
            counters['features'] += 1
            if counters['features'] > limits.features:
                raise ValueError('Regional feature budget exceeded; no index published.')
            fid = counters['features']
            feature = osm._feature(kind, ident, coords, tags)
            fields = dict(tags)
            if (fields.get('addr:housenumber') and
                    (fields.get('addr:street') or fields.get('addr:place')) and
                    not fields.get('addr:interpolation')):
                counters['address_features'] += 1
            west, east = min(c[0] for c in coords), max(c[0] for c in coords)
            south, north = min(c[1] for c in coords), max(c[1] for c in coords)
            searchable = _normalize(' '.join([ident, feature.name, kind] +
                                             [k + ' ' + v for k, v in tags]))
            result.execute('INSERT INTO features VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                           (fid, ident, feature.name, kind, _coords_blob(coords), _json(tags),
                            searchable, west, east, south, north))
            result.execute('INSERT INTO feature_bounds VALUES (?,?,?,?,?)',
                           (fid, west, east, south, north))
            if fts:
                result.execute('INSERT INTO feature_search(rowid,search) VALUES (?,?)',
                               (fid, searchable))
            if extent is None:
                extent = [west, south, east, north]
            else:
                extent = [min(extent[0], west), min(extent[1], south),
                          max(extent[2], east), max(extent[3], north)]

        reader = PBFStream(source, limits=limits, cancel=cancel, progress=progress)
        for kind, ident, payload, tags in reader:
            if kind == 'node':
                lon, lat = payload
                spool.execute('INSERT INTO nodes VALUES (?,?,?,?)',
                              (ident, lon, lat, _json(tags)))
                emit(f'node/{ident}', (payload,), tags)
            elif kind == 'way':
                spool.execute('INSERT INTO ways VALUES (?,?,?)',
                              (ident, struct.pack('<' + 'q' * len(payload), *payload), _json(tags)))
            else:
                spool.execute('INSERT INTO relations VALUES (?)', (ident,))
        if expected_sha256 is not None and reader.receipt['source_sha256'] != expected_sha256:
            raise ValueError('Source checksum mismatch; no index published.')
        spool.commit()
        ways = reader.counts['ways']
        for index, (ident, blob, raw_tags) in enumerate(spool.execute('SELECT id,refs,tags FROM ways')):
            osm._check(cancel)
            refs = [i[0] for i in struct.iter_unpack('<q', blob)]
            tags = tuple(tuple(t) for t in json.loads(raw_tags))
            if len(refs) < 2 or not osm._kind(tags):
                counters['omitted_ways'] += 1
                continue
            found = {}
            unique = sorted(set(refs))
            for start in range(0, len(unique), 400):
                osm._check(cancel)
                chunk = unique[start:start + 400]
                rows = spool.execute('SELECT id,lon,lat FROM nodes WHERE id IN (' +
                                     ','.join('?' for _ in chunk) + ')', chunk)
                found.update((r[0], (r[1], r[2])) for r in rows)
            if len(found) != len(unique):
                counters['missing_node_ways'] += 1
            else:
                emit(f'way/{ident}', tuple(found[r] for r in refs), tags)
            if progress and index % 128 == 0:
                progress(70 + 25 * index // max(1, ways), 100)
        if signature(source) != before:
            raise ValueError('Source changed before index publication.')
        metadata = dict(format='fieldforge-regional-index-v1', state='visual-search-only',
                        created_utc=datetime.now(timezone.utc).isoformat(),
                        attribution=ATTRIBUTION, license='ODbL-1.0',
                        license_url='https://opendatacommons.org/licenses/odbl/1-0/',
                        notice=NOTICE, bounds=extent, fts=fts, lookup_profile='explicit-tags-v1',
                        **reader.receipt, **counters)
        if origin is not None:
            metadata['origin'] = origin
        result.execute('INSERT INTO metadata VALUES (?,?)', ('receipt', _json(metadata)))
        result.commit()
        osm._check(cancel)
        if result.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Prepared database integrity check failed.')
        if result.execute("SELECT rtreecheck('feature_bounds')").fetchone()[0] != 'ok':
            raise ValueError('Prepared spatial index integrity check failed.')
        result.close()
        result = None
        spool.close()
        spool = None
        with output.open('r+b') as f:
            f.flush()
            os.fsync(f.fileno())
        osm._check(cancel)
        _publish_index(output, target)
        output = None
        if progress:
            progress(100, 100)
        return PreparedIndex(target.absolute(), signature(target), metadata)
    except sqlite3.IntegrityError as exc:
        raise ValueError('Duplicate OSM identity or invalid index row; no index published.') from exc
    except sqlite3.Error as exc:
        osm._check(cancel)
        raise ValueError('Regional database operation failed: ' + str(exc)) from exc
    finally:
        if result is not None:
            result.close()
        if spool is not None:
            spool.close()
        _remove_temporary(work)
        _remove_temporary(output)


def _bounds(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in value)):
        raise ValueError('Invalid index/query bounds.')
    w, s, e, n = value
    if not -180 <= w <= e <= 180 or not -MAX_LATITUDE <= s <= n <= MAX_LATITUDE:
        raise ValueError('Index/query bounds outside map coverage.')
    return tuple(value)


def _receipt(con):
    rows = con.execute('SELECT key,value FROM metadata').fetchmany(3)
    if len(rows) != 1 or rows[0][0] != 'receipt' or not isinstance(rows[0][1], str):
        raise ValueError('Invalid prepared-index metadata.')
    if len(rows[0][1].encode('utf8')) > META_LIMIT:
        raise ValueError('Prepared-index metadata exceeds limit.')
    try:
        data = json.loads(rows[0][1])
    except (ValueError, RecursionError) as exc:
        raise ValueError('Invalid prepared-index JSON receipt.') from exc
    if (not isinstance(data, dict) or data.get('format') != 'fieldforge-regional-index-v1'
            or data.get('state') != 'visual-search-only'
            or not isinstance(data.get('fts'), bool)
            or not isinstance(data.get('source_sha256'), str)
            or not re.fullmatch('[0-9a-f]{64}', data['source_sha256'])):
        raise ValueError('Unsupported or malformed prepared-index receipt.')
    for key in ('nodes', 'ways', 'relations', 'references', 'restrictions', 'features',
                'source_bytes', 'omitted_ways', 'missing_node_ways', 'polar_features',
                'dateline_features'):
        if type(data.get(key)) is not int or not 0 <= data[key] <= 50_000_000_000:
            raise ValueError('Invalid prepared-index count.')
    if 'bounds' not in data:
        raise ValueError('Prepared-index receipt lacks bounds.')
    if data['bounds'] is not None:
        _bounds(data['bounds'])
    if data['features'] > 0 and data['bounds'] is None:
        raise ValueError('Nonempty index lacks bounds.')
    if 'lookup_profile' in data or 'address_features' in data:
        if (data.get('lookup_profile') != 'explicit-tags-v1'
                or type(data.get('address_features')) is not int
                or not 0 <= data['address_features'] <= data['features']):
            raise ValueError('Invalid address-lookup profile/count.')
    timestamp = data.get('replication_timestamp')
    if timestamp is not None and (type(timestamp) is not int or not 0 <= timestamp <= 253402300799):
        raise ValueError('Invalid source snapshot timestamp.')
    for key in ('source_name', 'created_utc', 'notice', 'attribution', 'license', 'license_url'):
        if not isinstance(data.get(key), str) or len(data[key]) > 1500:
            raise ValueError('Invalid prepared-index text metadata.')
    return data


@contextmanager
def _connect(path, *, fingerprint=None, cancel=None, seconds=4):
    path = Path(path).absolute()
    before = signature(path)
    if fingerprint is not None and before != fingerprint:
        raise ValueError('Prepared map changed on disk. Reopen and verify it before use.')
    if not 1 <= before[2] <= 4 * 1024**3:
        raise ValueError('Prepared index is empty or exceeds the read budget.')
    for suffix in ('-journal', '-wal', '-shm'):
        if Path(str(path) + suffix).exists():
            raise ValueError('Prepared map has an active SQLite sidecar; close its writer.')
    osm._check(cancel)
    con = None
    until = time.monotonic() + seconds
    try:
        con = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)
        con.execute('PRAGMA query_only=ON')
        con.execute('PRAGMA trusted_schema=OFF')
        con.execute('PRAGMA cache_size=-8192')
        if hasattr(con, 'setlimit'):
            con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 2 * 1024**2)
            con.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 100000)
        con.set_progress_handler(lambda: int(
            (cancel is not None and cancel.is_set()) or time.monotonic() > until), 1000)
        if (con.execute('PRAGMA application_id').fetchone()[0] != APP_ID
                or con.execute('PRAGMA user_version').fetchone()[0] != VERSION):
            raise ValueError('Not a supported FieldForge regional index.')
        objects = con.execute("SELECT type,name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'").fetchall()
        if any(t in ('view', 'trigger') for t, _, _ in objects):
            raise ValueError('Views/triggers are not permitted in a prepared map.')
        allowed = {'metadata', 'features', 'feature_bounds', 'feature_bounds_node',
                   'feature_bounds_rowid', 'feature_bounds_parent', 'feature_search',
                   'feature_search_data', 'feature_search_idx', 'feature_search_content',
                   'feature_search_docsize', 'feature_search_config'}
        if any(name not in allowed for _, name, _ in objects):
            raise ValueError('Unexpected tables in prepared map.')
        definitions = {name: sql for typ, name, sql in objects if typ == 'table'}
        for name, statement in zip(('metadata', 'features'), SCHEMA.strip().split(';')[:2]):
            actual = definitions.get(name, '')
            if ' '.join(actual.split()) != ' '.join(statement.split()):
                raise ValueError('Unsupported prepared-map table schema.')
        for table, expected in (
                ('feature_bounds', 'CREATE VIRTUAL TABLE feature_bounds USING rtree(fid, west, east, south, north)'),
                ('feature_search', FTS_SCHEMA)):
            actual = definitions.get(table)
            if table == 'feature_bounds' and actual is None:
                raise ValueError('Prepared map is missing its spatial index.')
            if actual is not None and actual != expected:
                raise ValueError('Unsupported prepared-map virtual table.')
        yield con
        osm._check(cancel)
        if signature(path) != before or any(Path(str(path) + suffix).exists() for suffix in ('-journal', '-wal', '-shm')):
            raise ValueError('Prepared map changed during the query; discard results.')
    except sqlite3.Error as exc:
        osm._check(cancel)
        if time.monotonic() > until:
            raise ValueError('Map query exceeded its time budget. Narrow the search or view.') from exc
        raise ValueError('Invalid or unreadable regional index: ' + str(exc)) from exc
    finally:
        if con is not None:
            con.close()


def inspect_index(path, *, cancel=None, progress=None):
    path = Path(path).absolute()
    before = signature(path)
    with _connect(path, fingerprint=before, cancel=cancel, seconds=30) as con:
        metadata = _receipt(con)
        if con.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Prepared-map integrity check failed.')
        if con.execute("SELECT rtreecheck('feature_bounds')").fetchone()[0] != 'ok':
            raise ValueError('Prepared-map spatial integrity check failed.')
        count = con.execute('SELECT COUNT(*) FROM features').fetchone()[0]
        boxes = con.execute('SELECT COUNT(*) FROM feature_bounds').fetchone()[0]
        if count != metadata['features'] or boxes != count:
            raise ValueError('Prepared-map feature count does not match receipt.')
        if con.execute('SELECT 1 FROM features f LEFT JOIN feature_bounds b '
                       'ON b.fid=f.fid WHERE b.fid IS NULL LIMIT 1').fetchone():
            raise ValueError('Prepared map is missing spatial records.')
        if metadata['fts']:
            if con.execute('SELECT COUNT(*) FROM feature_search').fetchone()[0] != count:
                raise ValueError('Prepared-map search count does not match receipt.')
    if progress:
        progress(100, 100)
    return PreparedIndex(path, before, metadata)


def import_archive(archive, target, *, cancel=None, progress=None):
    """Validate and publish only the single map.ffmap member from a package ZIP."""
    archive, target = Path(archive), Path(target)
    if target.suffix.casefold() != '.ffmap':
        raise ValueError('Choose a new output filename ending in .ffmap.')
    if target.exists() or target.is_symlink():
        raise FileExistsError('An output already exists; choose a new .ffmap filename.')
    if not target.parent.is_dir():
        raise ValueError('Choose an existing output folder.')
    source, before = checked_open(archive)
    if not 1 <= before[2] <= MAX_ARCHIVE_BYTES:
        source.close()
        raise ValueError('Regional ZIP is empty or exceeds the 2 GiB archive limit.')
    temporary = None
    try:
        with source, zipfile.ZipFile(source) as package:
            members = package.infolist()
            if len(members) > 1000:
                raise ValueError('Regional ZIP contains more than 1,000 entries.')
            matches = [item for item in members
                       if item.filename.rstrip('/\\').rsplit('/', 1)[-1].casefold() == 'map.ffmap']
            if len(matches) != 1:
                raise ValueError('Package must contain exactly one map.ffmap index.')
            member = matches[0]
            parts = member.filename.replace('\\', '/').split('/')
            mode = (member.external_attr >> 16) & 0xFFFF
            file_type = stat.S_IFMT(mode)
            if (member.is_dir() or any(part in ('', '.', '..') for part in parts)
                    or member.filename.startswith(('/', '\\'))
                    or file_type not in (0, stat.S_IFREG)):
                raise ValueError('The map.ffmap ZIP entry is not a safe regular file.')
            if member.flag_bits & 1:
                raise ValueError('Encrypted regional ZIP entries are not supported.')
            if member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ValueError('Regional ZIP uses an unsupported compression method.')
            if not 1 <= member.file_size <= MAX_ARCHIVE_INDEX_BYTES:
                raise ValueError('Packaged index is empty or exceeds the 4 GiB index limit.')
            if member.file_size > max(1, member.compress_size) * 1000:
                raise ValueError('Packaged index compression ratio exceeds the safety limit.')
            osm._check(cancel)
            temporary = _temp(target.parent, '.archive.ffmap')
            written = 0
            with package.open(member, 'r') as packed, temporary.open('wb') as output:
                while True:
                    osm._check(cancel)
                    chunk = packed.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > member.file_size or written > MAX_ARCHIVE_INDEX_BYTES:
                        raise ValueError('Packaged index expanded beyond its declared size.')
                    output.write(chunk)
                    if progress:
                        progress(written, member.file_size)
                output.flush()
                os.fsync(output.fileno())
            if written != member.file_size:
                raise ValueError('Packaged index size does not match the ZIP directory.')
        if signature(archive) != before:
            raise ValueError('Regional ZIP changed during import; no index was published.')
        validated = inspect_index(temporary, cancel=cancel, progress=progress)
        osm._check(cancel)
        _publish_index(temporary, target)
        temporary = None
        fingerprint = signature(target)
        return PreparedIndex(target.absolute(), fingerprint, validated.metadata)
    except (zipfile.BadZipFile, EOFError, RuntimeError) as exc:
        raise ValueError('Regional ZIP or contained map index is damaged.') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _feature(row):
    ident, name, kind, blob, raw_tags = row
    if (not all(isinstance(v, str) and len(v) <= 1500 for v in (ident, name, kind))
            or not re.fullmatch(r'(node|way)/[1-9][0-9]{0,18}', ident)
            or not isinstance(blob, bytes) or not 16 <= len(blob) <= 160000
            or len(blob) % 16 or not isinstance(raw_tags, str) or len(raw_tags) > 131072):
        raise ValueError('Invalid indexed feature.')
    geometry = tuple(struct.iter_unpack('<dd', blob))
    if any(not math.isfinite(lon) or not math.isfinite(lat)
           or not -180 <= lon <= 180 or not -MAX_LATITUDE <= lat <= MAX_LATITUDE
           for lon, lat in geometry):
        raise ValueError('Invalid indexed feature coordinate.')
    tags = json.loads(raw_tags)
    if (not isinstance(tags, list) or len(tags) > 128
            or any(not isinstance(t, list) or len(t) != 2
                   or any(not isinstance(v, str) or len(v) > 16384 for v in t) for t in tags)):
        raise ValueError('Invalid indexed feature tags.')
    return osm.StreetFeature(ident, name, kind, geometry, tuple(tuple(t) for t in tags))


def _collect(rows, limit):
    results, points, limited = [], 0, False
    for row in rows:
        if len(results) >= limit:
            limited = True
            break
        feature = _feature(row)
        if points + len(feature.geometry) > MAX_QUERY_POINTS:
            limited = True
            break
        results.append(feature)
        points += len(feature.geometry)
    return IndexResults(tuple(results), limited)


def _limit(value):
    if type(value) is not int or not 1 <= value <= MAX_QUERY_FEATURES:
        raise ValueError('Query limit must be an integer from 1 to 1000.')


def search_index(index: PreparedIndex, query, *, limit=100, cancel=None):
    _limit(limit)
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError('Use a search of no more than 200 characters.')
    terms = _normalize(query).split()
    if len(terms) > 16:
        raise ValueError('Use no more than 16 search terms.')
    if query.strip() and not terms:
        return IndexResults((), False)
    with _connect(index.path, fingerprint=index.fingerprint, cancel=cancel) as con:
        columns = 'f.osm_id,f.name,f.kind,f.geometry,f.tags'
        if index.metadata['fts'] and terms:
            match = ' AND '.join('"' + t + '"*' for t in terms)
            rows = con.execute(f'SELECT {columns} FROM feature_search s JOIN features f '
                               'ON f.fid=s.rowid WHERE feature_search MATCH ? ORDER BY f.fid LIMIT ?',
                               (match, limit + 1))
        else:
            where = ' AND '.join('instr(f.search,?) > 0' for _ in terms) or '1'
            rows = con.execute(f'SELECT {columns} FROM features f WHERE {where} '
                               'ORDER BY f.fid LIMIT ?', (*terms, limit + 1))
        return _collect(rows, limit)


def feature_coordinate(feature: osm.StreetFeature) -> tuple[float, float, bool] | None:
    """Return (latitude, longitude, is_source_point) for an indexed feature.

    Point features retain their source coordinate. For lines/areas, return only
    the center of the feature bounds; that is a display aid, not an address or
    entrance coordinate.
    """
    if not feature.geometry:
        return None
    if len(feature.geometry) == 1:
        longitude, latitude = feature.geometry[0]
        return latitude, longitude, True
    longitudes = [point[0] for point in feature.geometry]
    latitudes = [point[1] for point in feature.geometry]
    return ((min(latitudes) + max(latitudes)) / 2,
            (min(longitudes) + max(longitudes)) / 2, False)


def visible_index(index: PreparedIndex, bounds, *, limit=700, cancel=None):
    """Return a bounded subset intersecting a WGS84 box. No unseen-edge routing."""
    _limit(limit)
    bounds = _bounds(bounds)
    w, s, e, n = bounds
    with _connect(index.path, fingerprint=index.fingerprint, cancel=cancel) as con:
        rows = con.execute('SELECT f.osm_id,f.name,f.kind,f.geometry,f.tags '
                           'FROM feature_bounds b JOIN features f ON f.fid=b.fid '
                           'WHERE b.east>=? AND b.west<=? AND b.north>=? AND b.south<=? '
                           'ORDER BY f.fid LIMIT ?', (w, e, s, n, limit + 1))
        return _collect(rows, limit)


def view_boxes(view: Viewport):
    """One or two query boxes, covering wrap without a world-spanning false gap."""
    left, top = view.origin
    size = 256 * 2**view.zoom
    north, west = unproject(left, max(0, min(size, top)), view.zoom)
    south, east = unproject(left + view.width, max(0, min(size, top + view.height)), view.zoom)
    if view.width >= size:
        return ((-180, south, 180, north),)
    if west <= east:
        return ((west, south, east, north),)
    return ((west, south, 180, north), (-180, south, east, north))


def viewport_index(index, view, *, cancel=None):
    features, ids, points, limited = [], set(), 0, False
    for box in view_boxes(view):
        page = visible_index(index, box, cancel=cancel)
        limited |= page.limited
        for feature in page.features:
            if feature.id not in ids:
                if len(features) >= 700 or points + len(feature.geometry) > MAX_QUERY_POINTS:
                    limited = True
                    break
                features.append(feature)
                ids.add(feature.id)
                points += len(feature.geometry)
    return IndexResults(tuple(features), limited)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline regional source index; not routing.')
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('prepare')
    build.add_argument('source', type=Path)
    build.add_argument('target', type=Path)
    info = sub.add_parser('inspect')
    info.add_argument('index', type=Path)
    search = sub.add_parser('search')
    search.add_argument('index', type=Path)
    search.add_argument('query')
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            index = prepare_index(args.source, args.target)
            print(json.dumps(index.metadata, indent=2))
        else:
            index = inspect_index(args.index)
            if args.command == 'inspect':
                print(json.dumps(index.metadata, indent=2))
            else:
                page = search_index(index, args.query)
                print(json.dumps({'limited': page.limited, 'features': [
                    {'id': f.id, 'name': f.name, 'kind': f.kind} for f in page.features]}, indent=2))
    except (OSError, ValueError, MapCancelled) as exc:
        parser.exit(2, 'FieldForge: ' + str(exc) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
