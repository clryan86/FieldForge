"""Integration with a separately installed FieldForge regional backend."""
import hashlib
import io
import socket
import stat
import struct
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ri = pytest.importorskip('fieldforge.navigation.region_install', reason='Regional source build required')
from tools.usa_maps import acquire as a
from tools.usa_maps import prepare as p


def varint(n):
    out = bytearray()
    while n > 127:
        out.append((n & 127) | 128)
        n >>= 7
    out.append(n)
    return bytes(out)


def number(k, n):
    return varint(k << 3) + varint(n)


def blob(k, raw):
    return varint((k << 3) | 2) + varint(len(raw)) + raw


def fileblock(kind, raw):
    body = blob(1, raw)
    header = blob(1, kind) + number(3, len(body))
    return struct.pack('>I', len(header)) + header + body


def tiny_osm():
    strings = (blob(1, b'') + blob(1, b'name') + blob(1, b'Fictional Test Road')
               + blob(1, b'highway') + blob(1, b'residential'))
    n1 = number(1, 2) + number(8, 0) + number(9, 0)
    n2 = number(1, 4) + number(8, 0) + number(9, 20000)
    way = number(1, 10) + blob(2, b'\x01\x03') + blob(3, b'\x02\x04') + blob(8, b'\x02\x02')
    group = blob(1, n1) + blob(1, n2) + blob(3, way)
    return (fileblock(b'OSMHeader', blob(4, b'OsmSchema-V0.6'))
            + fileblock(b'OSMData', blob(1, strings) + blob(2, group)))


class Reply(io.BytesIO):
    def __init__(self, raw, url):
        super().__init__(raw)
        self.url = url
        self.headers = {'Content-Length': str(len(raw))}

    def geturl(self):
        return self.url


@pytest.fixture
def sources(tmp_path):
    root = tmp_path / 'source'
    out = tmp_path / 'packs'
    root.mkdir()
    out.mkdir()
    data = tiny_osm()

    def tx(url):
        if url.endswith('.md5'):
            raw = (hashlib.md5(data).hexdigest() + '  vermont-latest.osm.pbf').encode()
        elif url.endswith('.pbf'):
            raw = data
        else:
            raw = b'fictional polygon\nEND\n'
        return Reply(raw, url)

    a.acquire_region(root, 'vermont', transport=tx)
    return root / 'vermont', out


def test_actual_pack_roundtrip_and_cached_resume(sources, monkeypatch):
    source, out = sources
    path, meta, reused = p.prepare_one(source, out)
    assert not reused and meta['map']['features'] == 1
    assert meta['roads']['state'] == 'not-requested'
    assert p.verify_pack(path, out) == meta
    before = path.read_bytes()

    def no_build(*args, **kwargs):
        raise AssertionError('Already-completed region must not rebuild')

    monkeypatch.setattr(ri, 'install_region', no_build)
    again, got, reused = p.prepare_one(source, out)
    assert reused and again == path and got == meta and path.read_bytes() == before


def test_offline_and_household_sentinel(sources, monkeypatch, tmp_path):
    source, out = sources
    before = {f.name: f.read_bytes() for f in source.iterdir()}
    sentinel = tmp_path / 'household.db'
    sentinel.write_bytes(b'private sentinel')

    def offline(*args, **kwargs):
        raise AssertionError('No network during preparation')

    monkeypatch.setattr(socket, 'socket', offline)
    path, meta, _ = p.prepare_one(source, out, try_roads=True)
    assert meta['roads']['state'] == 'prepared-experimental'
    assert path.is_file() and sentinel.read_bytes() == b'private sentinel'
    assert before == {f.name: f.read_bytes() for f in source.iterdir()}


def test_optional_road_failure_visible_not_suppressed(sources, monkeypatch):
    def no_graph(*args, **kwargs):
        raise ValueError('unsupported restriction in fictional source')

    monkeypatch.setattr(ri.roads, 'prepare_road_pack', no_graph)
    _, meta, _ = p.prepare_one(*sources, try_roads=True)
    assert meta['roads']['state'] == 'unavailable'
    assert 'unsupported restriction' in meta['roads']['reason']
    assert 'roads' not in meta['files']


def test_bad_snapshot_corruption_refused(sources):
    source, out = sources
    path, _, _ = p.prepare_one(source, out)
    path.write_bytes(b'corrupt archive')
    with pytest.raises(ValueError):
        p.prepare_one(source, out)
    assert path.read_bytes() == b'corrupt archive'


def test_incomplete_existing_job_is_not_replaced(sources):
    source, out = sources
    path, _, _ = p.prepare_one(source, out)
    (path.parent / 'prepared-job.json').unlink()
    before = path.read_bytes()
    with pytest.raises(OSError):
        p.prepare_one(source, out)
    assert path.read_bytes() == before


def test_failure_cleans_only_own_build(sources, monkeypatch):
    source, out = sources
    keep = out / 'keep'
    keep.write_text('unrelated')

    def fail(*args, **kwargs):
        raise ValueError('deliberate build failure')

    monkeypatch.setattr(ri, 'install_region', fail)
    with pytest.raises(ValueError):
        p.prepare_one(source, out)
    assert list(out.iterdir()) == [keep]


def test_source_sha_is_checked(sources):
    source, out = sources
    path, meta, _ = p.prepare_one(source, out)
    with pytest.raises(ValueError, match='different source'):
        p.verify_pack(path, out, expected_source='0' * 64)


def test_provenance_is_preserved_in_permitted_member(sources):
    path, _, _ = p.prepare_one(*sources)
    with zipfile.ZipFile(path) as z:
        rights = z.read('SOURCE-RIGHTS.txt').decode()
        assert a.BASE + 'vermont-latest.osm.pbf' in rights
        assert 'ODbL' in rights and 'ACQUISITION RECEIPT' in rights
        assert set(z.namelist()) == {'region.json', 'map.ffmap', 'source.osm.pbf', 'SOURCE-RIGHTS.txt'}


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'extra.txt', 'folder/file'])
def test_extra_archive_paths_rejected(sources, tmp_path, name):
    original, _, _ = p.prepare_one(*sources)
    changed = tmp_path / 'changed.zip'
    with zipfile.ZipFile(original) as src, zipfile.ZipFile(changed, 'w') as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info))
        dst.writestr(name, b'evil')
    with pytest.raises(ValueError):
        p.verify_pack(changed, tmp_path)
    assert not (tmp_path / 'escape').exists()


def test_symlink_zip_member_refused(sources, tmp_path):
    original, _, _ = p.prepare_one(*sources)
    changed = tmp_path / 'changed.zip'
    with zipfile.ZipFile(original) as src, zipfile.ZipFile(changed, 'w') as dst:
        for info in src.infolist():
            raw = src.read(info)
            if info.filename == 'map.ffmap':
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            dst.writestr(info, raw)
    with pytest.raises(ValueError):
        p.verify_pack(changed, tmp_path)


def test_existing_zip_output_not_clobbered(sources, tmp_path):
    source, out = sources
    built = ri.install_region(source / 'vermont-latest.osm.pbf', out, 'Fictional source')
    old = tmp_path / 'existing.zip'
    old.write_bytes(b'keep')
    with pytest.raises(ValueError):
        p.export_region(built.folder, old)
    assert old.read_bytes() == b'keep'


def test_no_hardlink_support_no_final_output(sources, tmp_path, monkeypatch):
    source, out = sources
    built = ri.install_region(source / 'vermont-latest.osm.pbf', out, 'Fictional source')

    def unavailable(*args, **kwargs):
        raise OSError('links unavailable')

    monkeypatch.setattr(p.os, 'link', unavailable)
    dest = tmp_path / 'new.zip'
    with pytest.raises(OSError):
        p.export_region(built.folder, dest)
    assert not dest.exists() and not list(tmp_path.glob('.pack-*'))


def test_no_backend_is_explicit(sources, monkeypatch):
    def unavailable():
        raise ValueError('regional-installer source build required')

    monkeypatch.setattr(p, 'backend', unavailable)
    with pytest.raises(ValueError, match='required'):
        p.prepare_one(*sources)
    assert list(sources[1].iterdir()) == []


def test_cli_rejects_invalid_region_no_path_escape(sources):
    source, out = sources
    assert p.main(['--source-root', str(source.parent), '--output', str(out),
                   '--regions', '../elsewhere']) == 2
    assert list(out.iterdir()) == []


def test_failed_manifest_hash_is_refused(sources, tmp_path):
    original, _, _ = p.prepare_one(*sources)
    changed = tmp_path / 'changed.zip'
    with zipfile.ZipFile(original) as src, zipfile.ZipFile(changed, 'w') as dst:
        for info in src.infolist():
            raw = src.read(info)
            if info.filename == 'SOURCE-RIGHTS.txt':
                raw = b'unexpected rights'
            dst.writestr(info, raw)
    with pytest.raises(ValueError):
        p.verify_pack(changed, tmp_path)
