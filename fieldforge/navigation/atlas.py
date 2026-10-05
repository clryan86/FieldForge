"""An offline catalog of real reference packs and approximate named locations.

No network, automatic download, address matching, location access or data writes.
Checksums detect changes against the selected manifest, not publisher identity.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from fieldforge.navigation.map_view import MAX_LATITUDE
from fieldforge.navigation.mbtiles import MapCancelled, inspect_pack

MAX_CATALOG = 128 * 1024
MAX_PLACES = 2 * 1024 * 1024
MAX_ATLAS_PACK = 512 * 1024 * 1024
_FILE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\Z')
_HASH = re.compile(r'[0-9a-f]{64}\Z')


def _text(value, limit=2048):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 for c in value)):
        raise ValueError('Invalid atlas text metadata.')
    return value


def _int(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid atlas integer metadata.')
    return value


def _digest(value):
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError('Invalid atlas SHA-256 metadata.')
    return value


def _path(root: Path, filename):
    if not isinstance(filename, str) or not _FILE.fullmatch(filename) or filename in ('.', '..'):
        raise ValueError('Atlas files must be named siblings of their catalog.')
    return root / filename


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate key in atlas JSON.')
        result[key] = value
    return result


def _json(raw):
    def nonfinite(_):
        raise ValueError('Non-finite number in atlas JSON.')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_object, parse_constant=nonfinite)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('Invalid atlas JSON.') from exc


def _signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def checked_bytes(path: Path, maximum: int, *, expected_size=None, digest=None,
                  cancel: Event | None = None, keep=True):
    """Read only a regular non-symlink file, bounded and checked before/after.

    Ordinary local file changes are detected. This is not a hostile-filesystem
    sandbox, a hard I/O deadline or a signature verification facility.
    """
    if cancel is not None and cancel.is_set():
        raise MapCancelled('Atlas operation cancelled.')
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= maximum:
        raise ValueError('Atlas file must be a regular, non-symlink file within the size limit.')
    if expected_size is not None and before.st_size != expected_size:
        raise ValueError('Atlas file size changed; restore the intended pack and manifest.')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
    h = hashlib.sha256()
    chunks = []
    count = 0
    with os.fdopen(fd, 'rb') as stream:
        if _signature(os.fstat(stream.fileno())) != _signature(before):
            raise ValueError('Atlas file changed before reading.')
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            if cancel is not None and cancel.is_set():
                raise MapCancelled('Atlas operation cancelled.')
            count += len(chunk)
            if count > maximum:
                raise ValueError('Atlas file exceeds its size limit.')
            h.update(chunk)
            if keep:
                chunks.append(chunk)
        if (_signature(os.fstat(stream.fileno())) != _signature(before)
                or _signature(path.lstat()) != _signature(before) or count != before.st_size):
            raise ValueError('Atlas file changed while reading.')
    if digest is not None and h.hexdigest() != digest:
        raise ValueError('Atlas checksum mismatch. No changed map will be opened.')
    if cancel is not None and cancel.is_set():
        raise MapCancelled('Atlas operation cancelled.')
    return b''.join(chunks) if keep else _signature(before)


@dataclass(frozen=True)
class AtlasPack:
    id: str
    title: str
    path: Path
    bytes: int
    sha256: str
    zooms: tuple[int, ...]
    tiles: int
    coverage: str
    notice: str


@dataclass(frozen=True)
class Atlas:
    path: Path
    title: str
    freshness: str
    packs: tuple[AtlasPack, ...]
    default: str
    places_path: Path
    places_sha256: str
    places_bytes: int
    place_count: int
    not_installed: tuple[str, ...]


@dataclass(frozen=True)
class AtlasPlace:
    id: str
    name: str
    kind: str
    latitude: float
    longitude: float
    zoom: int
    source: str
    pack_id: str = ""


def load_catalog(path: str | Path) -> Atlas:
    path = Path(path).expanduser().absolute()
    data = _json(checked_bytes(path, MAX_CATALOG))
    try:
        if type(data) is not dict or type(data['schema']) is not int or data['schema'] != 1:
            raise ValueError('Unsupported atlas catalog schema.')
        raw_packs = data['packs']
        if type(raw_packs) is not list or not 1 <= len(raw_packs) <= 32:
            raise ValueError('Atlas catalog needs 1 through 32 map packs.')
        packs, ids, paths = [], set(), set()
        for item in raw_packs:
            ident = _text(item['id'], 80)
            filename = _path(path.parent, item['file'])
            if ident in ids or filename.name.casefold() in paths or not filename.name.endswith('.mbtiles'):
                raise ValueError('Duplicate or invalid atlas pack.')
            ids.add(ident)
            paths.add(filename.name.casefold())
            if item.get('routing') is not False:
                raise ValueError('This atlas catalog supports reference imagery only, not routable graphs.')
            zs = item['zooms']
            if type(zs) is not list or not 1 <= len(zs) <= 23:
                raise ValueError('Invalid atlas zooms.')
            zooms = tuple(_int(z, 0, 22) for z in zs)
            if tuple(sorted(set(zooms))) != zooms:
                raise ValueError('Atlas zooms must be unique and sorted.')
            packs.append(AtlasPack(ident, _text(item['title']), filename,
                _int(item['bytes'], 16, MAX_ATLAS_PACK), _digest(item['sha256']), zooms,
                _int(item['tiles'], 1, 10000000), _text(item['coverage']), _text(item['notice'])))
        default = _text(data['default'], 80)
        if default not in ids:
            raise ValueError('Atlas default pack is not installed in its catalog.')
        missing = data['not_installed']
        if type(missing) is not list or len(missing) > 30:
            raise ValueError('Invalid atlas missing-capability metadata.')
        return Atlas(path, _text(data['title']), _text(data['freshness']), tuple(packs), default,
            _path(path.parent, data['places_file']), _digest(data['places_sha256']),
            _int(data['places_bytes'], 1, MAX_PLACES), _int(data['place_count'], 0, 10000),
            tuple(_text(x) for x in missing))
    except (KeyError, TypeError) as exc:
        raise ValueError('Incomplete or malformed atlas catalog.') from exc


def verify_pack(pack: AtlasPack, *, cancel: Event | None = None):
    signature = checked_bytes(pack.path, MAX_ATLAS_PACK, expected_size=pack.bytes,
                              digest=pack.sha256, cancel=cancel, keep=False)
    info = inspect_pack(pack.path, cancel=cancel)
    if info.signature != signature or info.zooms != pack.zooms:
        raise ValueError('Atlas pack changed or its observed zooms do not match the catalog.')
    return info


def load_places(atlas: Atlas, *, cancel: Event | None = None) -> tuple[AtlasPlace, ...]:
    data = _json(checked_bytes(atlas.places_path, MAX_PLACES, expected_size=atlas.places_bytes,
                              digest=atlas.places_sha256, cancel=cancel))
    try:
        if (type(data) is not dict or type(data['schema']) is not int or data['schema'] != 1
                or type(data['places']) is not list or len(data['places']) != atlas.place_count):
            raise ValueError('Invalid atlas places schema or count.')
        places, ids = [], set()
        for item in data['places']:
            ident = _text(item['id'], 80)
            if ident in ids:
                raise ValueError('Duplicate atlas place ID.')
            ids.add(ident)
            lat, lon = item['latitude'], item['longitude']
            if (type(lat) not in (int, float) or type(lon) not in (int, float)
                    or not math.isfinite(lat) or not math.isfinite(lon)
                    or not -MAX_LATITUDE <= lat <= MAX_LATITUDE or not -180 <= lon <= 180):
                raise ValueError('Invalid atlas reference coordinates.')
            pack_id = item.get('pack_id', '')
            if not isinstance(pack_id, str) or (pack_id and pack_id not in {p.id for p in atlas.packs}):
                raise ValueError('Atlas reference points must name an installed pack, or no pack.')
            places.append(AtlasPlace(ident, _text(item['name'], 300), _text(item['kind'], 200),
                float(lat), float(lon), _int(item['zoom'], 0, 22), _text(item['source'], 500), pack_id))
        return tuple(places)
    except (KeyError, TypeError) as exc:
        raise ValueError('Malformed atlas place index.') from exc


def _fold(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold())
                   if not unicodedata.combining(c))


def find_places(places, query: str, limit: int = 60) -> tuple[AtlasPlace, ...]:
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError('Use at most 200 characters for an atlas name search.')
    _int(limit, 1, 100)
    terms = _fold(query).split()
    matches = [p for p in places if all(t in _fold(p.name) for t in terms)]
    matches.sort(key=lambda p: (not _fold(p.name).startswith(_fold(query).strip()), _fold(p.name), p.id))
    return tuple(matches[:limit])


def bundled_catalog() -> Path | None:
    """An explicit environment override can disable automatic discovery with ''."""
    override = os.environ.get('FIELDFORGE_MAP_CATALOG')
    if override is not None:
        return Path(override).expanduser() if override else None
    path = Path(__file__).resolve().parents[2] / 'map-library' / 'catalog.json'
    return path if path.is_file() else None
