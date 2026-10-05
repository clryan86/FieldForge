"""Prepare explicitly selected collection ZIPs for the existing map publisher.

Only the archive bytes and contained display/search index are verified here.
Source PBF fingerprints and road status remain declarations from their receipts;
no raw source, road database, network service or device installation is processed.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fieldforge.navigation.mbtiles import MapCancelled
from fieldforge.navigation.pbf_stream import checked_open, signature
from fieldforge.navigation.regional_index import (
    MAX_ARCHIVE_BYTES,
    MAX_ARCHIVE_INDEX_BYTES,
    import_archive,
)
from fieldforge.online.catalog import MAX_CATALOG_MAPS, CatalogError, _asset, _signature
from fieldforge.online.map_validation import regional_file_preflight
from fieldforge.online.models import (
    MAX_JSON_BYTES,
    decode_json,
    encode_json,
    object_fields,
    safe_filename,
    text,
    validate_timestamp,
)
from fieldforge.online.storage import _publish_new_path

COLLECTION_FORMAT = 'fieldforge-map-collection-v1'
RECEIPT_FORMAT = 'fieldforge-map-collection-preparation-v1'
MAX_COUNT = 50_000_000_000
MAX_DECLARED_BYTES = (1 << 53) - 1
CHUNK_BYTES = 1024 * 1024
INVENTORY_FIELDS = ('id', 'title', 'filename', 'coverage', 'version',
                    'source', 'attribution', 'license')
PACK_FIELDS = {
    'filename', 'bytes', 'sha256', 'region_id', 'label', 'source_name',
    'source_sha256', 'replication_timestamp', 'expanded_bytes', 'map_features',
    'address_tagged_objects', 'missing_node_ways', 'road_preparation', 'license',
    'status', 'installed_on_device', 'validated_navigation',
}
NOTICE = (
    'Only selected archive bytes and prepared display/search indexes were verified. '
    'Source fingerprints and road preparation are receipt declarations; no source PBF, '
    'routing, device installation or navigation validation was performed.'
)


def _cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise MapCancelled('Regional collection preparation cancelled; no new inventory is ready.')


def _integer(value, name, maximum, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise CatalogError(f'{name} must be an integer from {minimum} to {maximum}.')


def _filename(value):
    if (not isinstance(value, str)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,179}', value)
            or not value.lower().endswith('.zip') or safe_filename(value) != value):
        raise CatalogError('Select portable ASCII ZIP basenames without paths or reserved names.')
    return value


def _digest(value, name):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise CatalogError(f'{name} must be a lowercase SHA-256 fingerprint.')


def _collection(data, filenames):
    object_fields(data, {'format', 'checked_utc', 'notice', 'packs', 'totals'}, 'Collection')
    if data['format'] != COLLECTION_FORMAT:
        raise CatalogError('Use a fieldforge-map-collection-v1 collection.')
    checked = validate_timestamp(data['checked_utc'], 'Collection checked_utc')
    if datetime.fromisoformat(checked.replace('Z', '+00:00')).utcoffset() != timedelta(0):
        raise CatalogError('Collection checked_utc must use UTC.')
    text(data['notice'], 'Collection notice', 4000, multiline=True)
    if not isinstance(data['totals'], dict):
        raise CatalogError('Collection totals must be an object; they are not verified coverage.')
    pending = [data]
    while pending:
        value = pending.pop()
        if isinstance(value, float) and not math.isfinite(value):
            raise CatalogError('Collection JSON must not contain non-finite numbers.')
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    packs = data['packs']
    if not isinstance(packs, list) or not 1 <= len(packs) <= MAX_CATALOG_MAPS:
        raise CatalogError('A collection must contain 1–5000 pack records.')
    entries, names, regions = {}, set(), set()
    for pack in packs:
        object_fields(pack, PACK_FIELDS, 'Collection pack')
        filename = _filename(pack['filename'])
        region = pack['region_id']
        if not isinstance(region, str) or not re.fullmatch('[0-9a-f]{32}', region):
            raise CatalogError('Collection region_id must contain 32 lowercase hexadecimal characters.')
        if filename.casefold() in names or region in regions:
            raise CatalogError('Collection filenames and region IDs must be distinct, including filename case.')
        names.add(filename.casefold())
        regions.add(region)
        _integer(pack['bytes'], 'Archive bytes', MAX_ARCHIVE_BYTES, 1)
        _integer(pack['expanded_bytes'], 'Declared expanded bytes', MAX_DECLARED_BYTES, 1)
        _digest(pack['sha256'], 'Archive sha256')
        _digest(pack['source_sha256'], 'Source sha256')
        text(pack['label'], 'Collection label', 500)
        text(pack['source_name'], 'Collection source name', 500)
        text(pack['license'], 'Collection license', 2000, multiline=True)
        if pack['replication_timestamp'] is not None:
            _integer(pack['replication_timestamp'], 'Source replication timestamp', 253402300799)
        _integer(pack['map_features'], 'Map features', MAX_COUNT)
        _integer(pack['address_tagged_objects'], 'Address-tagged objects', pack['map_features'])
        _integer(pack['missing_node_ways'], 'Missing-node ways', MAX_COUNT)
        road = object_fields(pack['road_preparation'], {'state', 'reason'}, 'Declared road preparation')
        text(road['state'], 'Declared road state', 80)
        if not isinstance(road['reason'], str):
            raise CatalogError('Declared road reason must be plain text.')
        if road['reason']:
            text(road['reason'], 'Declared road reason', 2000, multiline=True)
        if (pack['status'] != 'verified-download' or pack['installed_on_device'] != 'not-checked'
                or pack['validated_navigation'] is not False):
            raise CatalogError('Use verified-download records with installation not checked and navigation not validated.')
        entries[filename] = pack
    if not isinstance(filenames, (list, tuple)) or not 1 <= len(filenames) <= MAX_CATALOG_MAPS:
        raise CatalogError('Explicitly select one or more collection ZIP filenames.')
    chosen, selected = [], set()
    for value in filenames:
        name = _filename(value)
        if name.casefold() in selected:
            raise CatalogError('Select each collection ZIP filename only once.')
        if name not in entries:
            raise CatalogError(f'Selected ZIP is not listed in the collection: {name}')
        selected.add(name.casefold())
        chosen.append(entries[name])
    return chosen


@dataclass(frozen=True)
class _FileIdentity:
    path: Path
    pathname: tuple
    descriptor: tuple

    def check_open(self, stream):
        if (_signature(os.fstat(stream.fileno())) != self.descriptor
                or signature(self.path) != self.pathname):
            raise CatalogError(f'Collection input changed during preparation: {self.path.name}')

    def check(self):
        stream, pathname = checked_open(self.path)
        with stream:
            if pathname != self.pathname:
                raise CatalogError(f'Collection input changed during preparation: {self.path.name}')
            self.check_open(stream)


@contextmanager
def _open_input(path, maximum, cancel):
    _cancelled(cancel)
    stream, before = checked_open(path)
    with stream:
        if not 1 <= before[2] <= maximum:
            raise CatalogError(f'Collection input is empty or exceeds its byte limit: {path.name}')
        opened = _signature(os.fstat(stream.fileno()))
        if opened[:4] != before[:4] or signature(path) != before:
            raise CatalogError(f'Collection input changed while opening: {path.name}')
        identity = _FileIdentity(path, before, opened)
        yield stream, identity
        _cancelled(cancel)
        identity.check_open(stream)


def _hash_input(stream, identity, cancel, *, keep_bytes=False):
    digest, size = hashlib.sha256(), 0
    chunks = []
    while True:
        _cancelled(cancel)
        chunk = stream.read(min(CHUNK_BYTES, identity.pathname[2] + 1 - size))
        if not chunk:
            break
        size += len(chunk)
        if size > identity.pathname[2]:
            raise CatalogError(f'Collection input grew during preparation: {identity.path.name}')
        digest.update(chunk)
        if keep_bytes:
            chunks.append(chunk)
    if size != identity.pathname[2]:
        raise CatalogError(f'Collection input size changed during preparation: {identity.path.name}')
    identity.check_open(stream)
    return digest.hexdigest(), b''.join(chunks) if keep_bytes else None


def _directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise CatalogError('Choose existing real local directories, without symbolic links.')
    return info.st_dev, info.st_ino


def _resolve_directory(path):
    before = _directory(path)
    resolved = path.resolve(strict=True)
    # Parent traversal and Windows short-name aliases can change the spelling
    # without changing the directory. Compare identity, not canonical text.
    _check_directory(resolved, before)
    return resolved, before


def _check_directory(path, expected):
    if _directory(path) != expected:
        raise CatalogError('A collection preparation directory changed; no new inventory is ready.')


def _check_inputs(inputs, cancel):
    for identity in inputs:
        _cancelled(cancel)
        identity.check()


def _map_record(pack, index, digest):
    meta = index.metadata
    for declared, recorded in (
        ('source_name', 'source_name'), ('source_sha256', 'source_sha256'),
        ('replication_timestamp', 'replication_timestamp'), ('map_features', 'features'),
        ('address_tagged_objects', 'address_features'), ('missing_node_ways', 'missing_node_ways'),
        ('license', 'license'),
    ):
        if pack[declared] != meta.get(recorded):
            raise CatalogError(f'Prepared index receipt disagrees with collection {declared}: {pack["filename"]}')
    if meta['features'] < 1:
        raise CatalogError('An empty regional index cannot be prepared for the portal.')
    snapshot = meta['replication_timestamp']
    version = ('source-sha256:' + meta['source_sha256'] if snapshot is None else
               (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=snapshot))
               .isoformat().replace('+00:00', 'Z'))
    map_id = 'regional-' + pack['region_id']
    asset = _asset({
        'id': map_id, 'title': pack['label'], 'filename': index.path.name,
        'format': 'ffmap', 'download_path': f'/api/v1/maps/{map_id}/download',
        'bytes': index.fingerprint[2], 'sha256': digest, 'coverage': meta['bounds'],
        'version': version, 'source': meta['source_name'],
        'attribution': meta['attribution'], 'license': meta['license'],
    })
    entry = {field: asset[field] for field in INVENTORY_FIELDS}
    record = {
        'id': map_id, 'region_id': pack['region_id'], 'title': asset['title'],
        'archive': {field: pack[field] for field in ('filename', 'bytes', 'sha256')},
        'map': {field: asset[field] for field in ('filename', 'bytes', 'sha256')},
        'source': {'name': meta['source_name'], 'bytes': meta['source_bytes'],
                   'sha256': meta['source_sha256'], 'replication_timestamp': snapshot,
                   'verification': 'receipt-matched-collection'},
        'coverage': asset['coverage'], 'version': version, 'attribution': asset['attribution'],
        'license': asset['license'], 'features': meta['features'],
        'address_features': meta['address_features'], 'missing_node_ways': meta['missing_node_ways'],
        'declared_road_preparation': dict(pack['road_preparation']),
    }
    return entry, record


def _write_json(path, value):
    raw = encode_json(value)
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _same_object(path, expected, mode):
    try:
        current = path.lstat()
    except FileNotFoundError:
        return False
    return (stat.S_IFMT(current.st_mode) == mode
            and (current.st_dev, current.st_ino) == expected)


def _rollback(output, root_identity, maps_identity, installed):
    if root_identity is None or not _same_object(output, root_identity, stat.S_IFDIR):
        return
    maps = output / 'maps'
    for path, identity in reversed(installed):
        if path.parent == maps and not _same_object(maps, maps_identity, stat.S_IFDIR):
            continue
        if _same_object(path, identity, stat.S_IFREG):
            path.unlink()
    for path, identity in ((maps, maps_identity), (output, root_identity)):
        if identity is not None and _same_object(path, identity, stat.S_IFDIR):
            try:
                path.rmdir()
            except OSError:
                # Never remove competing files or directories to complete rollback.
                pass


def _publish(stage, output, names, inputs, parent_identity, cancel):
    root_identity = maps_identity = None
    installed = []
    try:
        _check_directory(output.parent, parent_identity)
        _cancelled(cancel)
        output.mkdir(mode=0o700)  # An atomic claim, even against a competing empty directory.
        root_identity = _directory(output)
        maps = output / 'maps'
        maps.mkdir(mode=0o700)
        maps_identity = _directory(maps)
        paths = [Path('maps') / name for name in names]
        paths += [Path('preparation-receipt.json'), Path('inventory.json')]
        for relative in paths:
            _cancelled(cancel)
            _check_directory(output.parent, parent_identity)
            _check_directory(output, root_identity)
            _check_directory(maps, maps_identity)
            if relative.name == 'inventory.json':
                _check_inputs(inputs, cancel)
            source, target = stage / relative, output / relative
            before = source.lstat()
            identity = before.st_dev, before.st_ino
            # Register ownership before the system call: an interruption just
            # after a link/rename still permits removal of only our own inode.
            installed.append((target, identity))
            _publish_new_path(source, target)
            if not _same_object(target, identity, stat.S_IFREG):
                raise CatalogError('A prepared output changed during publication.')
        _check_inputs(inputs, cancel)
        _check_directory(output.parent, parent_identity)
        _check_directory(output, root_identity)
        _check_directory(maps, maps_identity)
        _cancelled(cancel)
    except BaseException:
        _rollback(output, root_identity, maps_identity, installed)
        raise


def prepare_collection(collection, archive_folder, output, *, filenames, cancel=None, progress=None):
    """Verify selected ZIPs and publish a NEW inventory directory.

    ``filenames`` is a nonempty list/tuple of exact collection ZIP basenames.
    ``progress(done, total, filename)`` runs after each privately prepared map.
    Cancellation uses ``cancel.is_set()`` and raises ``MapCancelled``. Input or
    integrity failures raise ``CatalogError``. Failures before the final publication
    checks complete roll back owned output; later staging cleanup failures or
    interruptions may leave the complete, committed inventory. A competing output
    or replacement path is never overwritten/deleted.
    The returned inventory/receipt paths and map_count are JSON-serializable.
    """
    try:
        collection = Path(collection).expanduser().absolute()
        archive_folder = Path(archive_folder).expanduser().absolute()
        output = Path(output).expanduser().absolute()
        _cancelled(cancel)
        if output.exists() or output.is_symlink():
            raise CatalogError('Choose a new output directory; existing paths are never replaced.')
        parent, parent_identity = _resolve_directory(output.parent)
        output = parent / output.name
        archive_folder, archive_identity = _resolve_directory(archive_folder)
        collection_parent, _ = _resolve_directory(collection.parent)
        collection = collection_parent / collection.name
        with _open_input(collection, MAX_JSON_BYTES, cancel) as (stream, collection_identity):
            collection_digest, raw = _hash_input(stream, collection_identity, cancel, keep_bytes=True)
        data = decode_json(raw)
        selected = _collection(data, filenames)
        inputs, map_inputs, entries, records = [collection_identity], [], [], []
        with tempfile.TemporaryDirectory(prefix='.fieldforge-collection-', dir=output.parent) as temporary:
            stage = Path(temporary)
            (stage / 'maps').mkdir(mode=0o700)
            for number, pack in enumerate(selected, 1):
                _check_directory(archive_folder, archive_identity)
                archive = archive_folder / pack['filename']
                with _open_input(archive, MAX_ARCHIVE_BYTES, cancel) as (stream, identity):
                    if identity.pathname[2] != pack['bytes']:
                        raise CatalogError(f'Archive size disagrees with the collection: {archive.name}')
                    digest, _ = _hash_input(stream, identity, cancel)
                    if digest != pack['sha256']:
                        raise CatalogError(f'Archive SHA-256 disagrees with the collection: {archive.name}')
                    target = stage / 'maps' / (pack['region_id'] + '.ffmap')
                    index = import_archive(archive, target, cancel=cancel)
                    if regional_file_preflight(target, cancel) != index.fingerprint:
                        raise CatalogError('The imported prepared index changed during verification.')
                    with _open_input(target, MAX_ARCHIVE_INDEX_BYTES, cancel) as (map_stream, map_identity):
                        if map_identity.pathname != index.fingerprint:
                            raise CatalogError('The imported prepared index changed before hashing.')
                        map_digest, _ = _hash_input(map_stream, map_identity, cancel)
                    entry, record = _map_record(pack, index, map_digest)
                inputs.append(identity)
                map_inputs.append(map_identity)
                entries.append(entry)
                records.append(record)
                if progress is not None:
                    progress(number, len(selected), pack['filename'])
                _cancelled(cancel)
            inventory = {'schema_version': 1, 'asset_folder': 'maps', 'maps': entries}
            receipt = {
                'format': RECEIPT_FORMAT, 'scope': 'display/search', 'notice': NOTICE,
                'collection': {'filename': collection.name, 'bytes': len(raw), 'sha256': collection_digest,
                               'checked_utc': data['checked_utc'], 'notice': data['notice']},
                'maps': records,
            }
            _write_json(stage / 'inventory.json', inventory)
            _write_json(stage / 'preparation-receipt.json', receipt)
            _check_inputs(inputs + map_inputs, cancel)
            _check_directory(archive_folder, archive_identity)
            for identity in map_inputs:
                if regional_file_preflight(identity.path, cancel) != identity.pathname:
                    raise CatalogError('A staged prepared index changed before publication.')
            _publish(stage, output, [entry['filename'] for entry in entries],
                     inputs, parent_identity, cancel)
        return {'inventory': str(output / 'inventory.json'),
                'receipt': str(output / 'preparation-receipt.json'), 'map_count': len(entries)}
    except MapCancelled:
        raise
    except CatalogError:
        raise
    except (ValueError, OSError) as exc:
        raise CatalogError(f'Collection preparation failed: {exc}') from exc
