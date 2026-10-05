"""A historical source basename is accepted only through its bound ZIP receipt."""

from __future__ import annotations

import copy
import hashlib
import json
import stat
import struct
import threading
import zipfile
from contextlib import nullcontext
from pathlib import Path

import pytest
from test_regional_collection import (
    assert_no_publication,
    make_case,
    prepare,
    refresh_archive,
    zip_entries,
)

from fieldforge.navigation import regional_index as regional
from fieldforge.navigation.mbtiles import MapCancelled
from fieldforge.online import collection
from fieldforge.online.catalog import CatalogError


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _wrapper(case):
    pack, index = case.document['packs'][0], case.indexes[0]
    meta, raw = index.metadata, index.path.read_bytes()
    return {
        'format': 'fieldforge-region-install-v1', 'state': 'complete',
        'id': pack['region_id'], 'label': pack['label'],
        'installed_utc': '2026-10-03T04:07:11.314318+00:00',
        'source': {'name': pack['source_name'], 'provenance': 'local-file',
                   'replication_timestamp': meta['replication_timestamp']},
        'map': {'state': 'prepared', 'features': meta['features'],
                'address_features': meta['address_features'],
                'missing_node_ways': meta['missing_node_ways']},
        'roads': copy.deepcopy(pack['road_preparation']),
        'files': {
            'source': {'bytes': meta['source_bytes'], 'sha256': meta['source_sha256']},
            'map': {'bytes': len(raw), 'sha256': _hash(raw)},
            'rights': {'bytes': len(b'TEST attribution'), 'sha256': _hash(b'TEST attribution')},
        },
        'license': meta['license'],
        'notice': 'TEST source/map declarations only; no driving directions.',
    }


def _write_alias(case, wrapper=None, *, folder='region-0', receipt_name=None,
                 extra=(), raw_receipt=None):
    prefix = folder + '/' if folder else ''
    if wrapper is None:
        wrapper = _wrapper(case)
    raw = (json.dumps(wrapper, ensure_ascii=False).encode('utf-8')
           if raw_receipt is None else raw_receipt)
    member_name = prefix + 'region.json' if receipt_name is None else receipt_name
    zip_entries(case, 0, [
        (prefix + 'map.ffmap', case.indexes[0].path.read_bytes()),
        (member_name, raw),
        (prefix + 'SOURCE-RIGHTS.txt', b'TEST attribution'),
        (prefix + 'source.osm.pbf', case.indexes[0].path.with_name('source.osm.pbf').read_bytes()),
        *extra,
    ])
    return raw


@pytest.fixture
def alias_case(tmp_path):
    case = make_case(tmp_path)
    case.document['packs'][0]['source_name'] = 'original-state-latest.osm.pbf'
    _write_alias(case)
    return case


@pytest.mark.parametrize('folder', ('', 'region-0'))
def test_bound_wrapper_preserves_index_and_all_three_source_name_representations(
    alias_case, monkeypatch, folder,
):
    case = alias_case
    raw_receipt = _write_alias(case, folder=folder)
    original = case.indexes[0].path.read_bytes()
    original_metadata = copy.deepcopy(case.indexes[0].metadata)
    pack = case.document['packs'][0]
    original_archive = (case.archives / pack['filename']).read_bytes()
    opened = []
    real_open = zipfile.ZipFile.open

    def only_map_and_wrapper(self, name, *args, **kwargs):
        filename = name.filename if isinstance(name, zipfile.ZipInfo) else name
        opened.append(filename)
        assert not filename.endswith('source.osm.pbf'), 'A source declaration must not imply PBF inspection'
        return real_open(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, 'open', only_map_and_wrapper)
    result = prepare(case)
    inventory = json.loads(Path(result['inventory']).read_bytes())
    note, = json.loads(Path(result['receipt']).read_bytes())['maps']
    entry, = inventory['maps']
    target = case.output / 'maps' / entry['filename']
    assert target.read_bytes() == original
    assert regional.inspect_index(target).metadata == original_metadata
    assert (case.archives / pack['filename']).read_bytes() == original_archive
    assert entry['source'] == pack['source_name'] == 'original-state-latest.osm.pbf'
    assert note['source']['name'] == original_metadata['source_name'] == 'source.osm.pbf'
    assert note['source']['declared_name'] == pack['source_name']
    assert note['source']['verification'] == 'archive-wrapper-matched-collection'
    binding = note['archive_receipt']
    prefix = folder + '/' if folder else ''
    assert binding['filename'] == prefix + 'region.json'
    assert binding['bytes'] == len(raw_receipt) and binding['sha256'] == _hash(raw_receipt)
    assert binding['format'] == 'fieldforge-region-install-v1'
    assert binding['region_id'] == pack['region_id']
    assert binding['map'] == {'bytes': len(original), 'sha256': _hash(original)}
    assert binding['source'] == {
        'name': pack['source_name'], 'embedded_name': original_metadata['source_name'],
        'bytes': original_metadata['source_bytes'], 'sha256': original_metadata['source_sha256'],
        'replication_timestamp': original_metadata['replication_timestamp'],
        'verification': 'receipt-declaration-only',
    }
    assert opened.count(prefix + 'region.json') == 1
    assert len(regional.search_index(regional.inspect_index(target), 'Map Street').features) == 2


def test_matching_source_names_keep_existing_behavior_without_interpreting_an_unneeded_wrapper(alias_case):
    case = alias_case
    pack = case.document['packs'][0]
    pack['source_name'] = case.indexes[0].metadata['source_name']
    _write_alias(case, raw_receipt=b'An unrelated, unused receipt')
    result = prepare(case)
    note, = json.loads(Path(result['receipt']).read_bytes())['maps']
    assert note['source']['verification'] == 'receipt-matched-collection'
    assert 'declared_name' not in note['source'] and 'archive_receipt' not in note
    assert json.loads(Path(result['inventory']).read_bytes())['maps'][0]['source'] == pack['source_name']


def test_missing_wrapper_does_not_turn_a_source_filename_mismatch_into_an_alias(alias_case):
    case = alias_case
    zip_entries(case, 0, [('map.ffmap', case.indexes[0].path.read_bytes())])
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError, match='filename mismatch'):
        prepare(case)
    assert_no_publication(case, before)


@pytest.mark.parametrize('path,value', (
    (('format',), 'fieldforge-region-install-v2'),
    (('state',), 'incomplete'),
    (('id',), 'f' * 32),
    (('label',), 'An unrelated region'),
    (('installed_utc',), 'not-a-timestamp'),
    (('source', 'name'), 'other-source.osm.pbf'),
    (('source', 'provenance'), None),
    (('source', 'replication_timestamp'), 1_700_000_001),
    (('source', 'replication_timestamp'), None),
    (('source', 'replication_timestamp'), True),
    (('map', 'state'), 'unavailable'),
    (('map', 'features'), 999),
    (('map', 'features'), True),
    (('map', 'address_features'), 999),
    (('map', 'missing_node_ways'), 999),
    (('files', 'map', 'sha256'), 'e' * 64),
    (('files', 'map', 'bytes'), 1),
    (('files', 'source', 'sha256'), 'e' * 64),
    (('files', 'source', 'bytes'), 1),
    (('files', 'source', 'bytes'), True),
    (('files', 'rights', 'sha256'), 'not-a-digest'),
    (('license',), 'CC0-1.0'),
    (('roads', 'state'), 'a-different-declaration'),
    (('notice',), {'unexpected': 'object'}),
))
def test_conflicting_or_malformed_wrapper_identity_is_rejected_without_publication(alias_case, path, value):
    case = alias_case
    wrapper = _wrapper(case)
    obj = wrapper
    for component in path[:-1]:
        obj = obj[component]
    obj[path[-1]] = value
    _write_alias(case, wrapper)
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError):
        prepare(case)
    assert_no_publication(case, before)


@pytest.mark.parametrize('damage', ('duplicate-key', 'malformed-utf8', 'oversized', 'empty', 'extra-field'))
def test_bounded_unambiguous_wrapper_json_is_required(alias_case, damage):
    case = alias_case
    wrapper = _wrapper(case)
    raw = json.dumps(wrapper).encode('utf-8')
    if damage == 'duplicate-key':
        raw = b'{"format":"fieldforge-region-install-v1",' + raw[1:]
    elif damage == 'malformed-utf8':
        raw = b'\xff'
    elif damage == 'oversized':
        raw = b' ' * (collection.MAX_REGION_RECEIPT_BYTES + 1)
    elif damage == 'empty':
        raw = b''
    else:
        wrapper['unsupported'] = 'field'
        raw = json.dumps(wrapper).encode('utf-8')
    _write_alias(case, raw_receipt=raw)
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError):
        prepare(case)
    assert_no_publication(case, before)


@pytest.mark.parametrize('name', (
    'region.json', 'other/region.json', '../region.json', '/region.json',
    'C:/region.json', 'region-0\\region.json', 'region-0/region.json/', 'region-0/REGION.JSON',
))
def test_alias_receipt_must_be_safe_and_adjacent_to_the_imported_index(alias_case, name):
    case = alias_case
    _write_alias(case, receipt_name=name)
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError):
        prepare(case)
    assert_no_publication(case, before)


@pytest.mark.parametrize('name', ('region-0/region.json', 'region-0/REGION.JSON', 'other/region.json'))
def test_duplicate_or_competing_region_receipts_are_never_selected_by_order(alias_case, name):
    case = alias_case
    with pytest.warns(UserWarning) if name == 'region-0/region.json' else nullcontext():
        _write_alias(case, extra=[(name, json.dumps(_wrapper(case)).encode('utf-8'))])
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError):
        prepare(case)
    assert_no_publication(case, before)


@pytest.mark.parametrize('kind', ('symlink', 'directory', 'fifo', 'bzip2'))
def test_receipt_must_be_an_ordinary_file_with_supported_compression(alias_case, kind):
    case = alias_case
    entry = zipfile.ZipInfo('region-0/region.json')
    entry.create_system = 3
    modes = {'symlink': stat.S_IFLNK, 'directory': stat.S_IFDIR, 'fifo': stat.S_IFIFO}
    if kind in modes:
        entry.external_attr = (modes[kind] | 0o600) << 16
    else:
        entry.compress_type = zipfile.ZIP_BZIP2
    _write_alias(case, receipt_name=entry)
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError):
        prepare(case)
    assert_no_publication(case, before)


def _damage_receipt_zip(case, *, encrypted=False):
    path = case.archives / case.document['packs'][0]['filename']
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo('region-0/region.json')
        central = archive.start_dir
    raw = bytearray(path.read_bytes())
    if encrypted:
        struct.pack_into('<H', raw, info.header_offset + 6, info.flag_bits | 1)
        while raw[central:central + 4] == b'PK\x01\x02':
            name_length, extra_length, comment_length = struct.unpack_from('<HHH', raw, central + 28)
            name = raw[central + 46:central + 46 + name_length].decode('utf-8')
            if name == info.filename:
                struct.pack_into('<H', raw, central + 8, info.flag_bits | 1)
                break
            central += 46 + name_length + extra_length + comment_length
        else:
            raise AssertionError('Receipt ZIP directory entry was not found')
    else:
        name_length, extra_length = struct.unpack_from('<HH', raw, info.header_offset + 26)
        offset = info.header_offset + 30 + name_length + extra_length
        raw[offset + info.file_size - 1] ^= 1
    path.write_bytes(raw)
    refresh_archive(case, 0)  # The outer ZIP identity passes; the receipt itself must still fail.


@pytest.mark.parametrize('encrypted', (False, True))
def test_crc_damaged_or_encrypted_wrapper_is_rejected_after_outer_archive_verification(alias_case, encrypted):
    case = alias_case
    _damage_receipt_zip(case, encrypted=encrypted)
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError):
        prepare(case)
    assert_no_publication(case, before)


def test_nul_truncated_wrapper_filename_is_not_accepted_as_region_json(alias_case):
    case = alias_case
    _write_alias(case, receipt_name='region-0/region.json-hidden')
    path = case.archives / case.document['packs'][0]['filename']
    raw = path.read_bytes().replace(b'region-0/region.json-hidden', b'region-0/region.json\x00hidden')
    path.write_bytes(raw)
    refresh_archive(case, 0)
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError):
        prepare(case)
    assert_no_publication(case, before)


def test_archive_replacement_during_wrapper_read_cannot_authorize_a_source_alias(alias_case, monkeypatch):
    case = alias_case
    original = collection._region_binding

    def replace_archive(*args):
        path = case.archives / case.document['packs'][0]['filename']
        replacement = path.with_suffix('.replacement')
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
        return original(*args)

    monkeypatch.setattr(collection, '_region_binding', replace_archive)
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError):
        prepare(case)
    assert_no_publication(case, before)


def test_cancellation_during_wrapper_validation_leaves_no_inventory(alias_case, monkeypatch):
    case = alias_case
    event = threading.Event()
    original = collection._region_binding

    def cancel_after_binding(*args):
        binding = original(*args)
        event.set()
        return binding

    monkeypatch.setattr(collection, '_region_binding', cancel_after_binding)
    before = set(case.root.iterdir())
    with pytest.raises(MapCancelled):
        prepare(case, cancel=event)
    assert_no_publication(case, before)


def test_agreeing_wrapper_does_not_override_a_disagreement_with_actual_index_metadata(alias_case):
    case = alias_case
    case.document['packs'][0]['license'] = 'CC0-1.0'
    wrapper = _wrapper(case)
    wrapper['license'] = 'CC0-1.0'
    _write_alias(case, wrapper)
    before = set(case.root.iterdir())
    with pytest.raises(CatalogError):
        prepare(case)
    assert_no_publication(case, before)
