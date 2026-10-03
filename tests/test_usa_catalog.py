"""Collection wrapper tests. Region contents are validated by the existing backend."""
import hashlib
import json
import socket
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.usa_maps import catalog as c


@pytest.fixture
def packs(tmp_path, monkeypatch):
    """Tiny ZIPs with a mocked backend, not real mapped geography."""
    workspace = tmp_path / 'work'; workspace.mkdir()
    metadata = {}
    paths = []
    for i, name in enumerate(('B.zip', 'A.zip'), 1):
        path = tmp_path / name
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('region.json', '{}')
            z.writestr('source.osm.pbf', str(i))
        meta = dict(id=f'{i:032x}', label=f'Fictional map {i}',
                    files={'source': {'sha256': f'{i:064x}', 'bytes': 1}},
                    source={'name': 'example.osm.pbf', 'replication_timestamp': None},
                    map={'features': i, 'address_features': 0, 'missing_node_ways': 0},
                    roads={'state': 'not-requested', 'reason': 'Not requested'}, license='ODbL-1.0')
        metadata[str(path)] = meta
        paths.append(path)
    monkeypatch.setattr(c, 'verify_pack', lambda p, w: metadata[str(p)])
    return paths, workspace, metadata


def test_sorted_totals_and_no_install_claim(packs):
    paths, workspace, _ = packs
    result = c.build_catalog(paths, workspace)
    assert [r['filename'] for r in result['packs']] == ['A.zip', 'B.zip']
    assert result['totals']['map_features'] == 3
    assert result['totals']['expanded_bytes'] == 6
    assert result['totals']['download_bytes'] == sum(p.stat().st_size for p in paths)
    for row in result['packs']:
        assert row['installed_on_device'] == 'not-checked'
        assert row['status'] == 'verified-download' and row['validated_navigation'] is False
        assert row['replication_timestamp'] is None
        assert row['sha256'] == hashlib.sha256((workspace.parent / row['filename']).read_bytes()).hexdigest()
    assert str(workspace.parent) not in json.dumps(result)


def test_write_offline_and_no_household_change(packs, monkeypatch):
    paths, workspace, _ = packs
    sentinel = workspace / 'household.db'; sentinel.write_bytes(b'private test sentinel')
    def deny(*args, **kwargs): raise AssertionError('No network')
    monkeypatch.setattr(socket, 'socket', deny)
    result = c.write_catalog(paths, workspace, workspace / 'maps.json')
    assert json.loads((workspace / 'maps.json').read_text()) == result
    assert sentinel.read_bytes() == b'private test sentinel'
    assert not list(workspace.glob('*.part'))


@pytest.mark.parametrize('name', ['existing.json', 'existing.JSON'])
def test_no_overwrite(packs, name):
    paths, workspace, _ = packs
    out = workspace / name;out.write_text('KEEP')
    with pytest.raises(ValueError): c.write_catalog(paths, workspace, out)
    assert out.read_text() == 'KEEP'


@pytest.mark.parametrize('name', ['maps.zip', 'maps.txt', 'maps'])
def test_output_suffix(packs, name):
    paths, workspace, _ = packs
    with pytest.raises(ValueError): c.write_catalog(paths, workspace, workspace / name)


def test_empty(packs):
    _, workspace, _ = packs
    with pytest.raises(ValueError, match='at least'): c.build_catalog([], workspace)


def test_maximum_iterable(packs):
    paths, workspace, _ = packs
    with pytest.raises(ValueError, match='128'): c.build_catalog((paths[0] for _ in range(129)), workspace)


def test_duplicate_input(packs):
    paths, workspace, _ = packs
    with pytest.raises(ValueError, match='filename'): c.build_catalog([paths[0], paths[0]], workspace)


def test_casefold_name_collision(packs):
    paths, workspace, _ = packs
    with pytest.raises(ValueError, match='filename'): c.build_catalog([paths[0], paths[0].with_name('b.ZIP')], workspace)


@pytest.mark.parametrize('field', ['identity', 'source'])
def test_duplicate_identity_or_source(packs, field):
    paths, workspace, metadata = packs
    one, two = (metadata[str(p)] for p in paths)
    if field == 'identity': two['id'] = one['id']
    else: two['files']['source']['sha256'] = one['files']['source']['sha256']
    with pytest.raises(ValueError, match='Duplicate region'): c.build_catalog(paths, workspace)


def test_failed_backend_leaves_no_report(packs, monkeypatch):
    paths, workspace, _ = packs
    def bad(*args): raise ValueError('Bad map')
    monkeypatch.setattr(c, 'verify_pack', bad)
    with pytest.raises(ValueError): c.write_catalog(paths, workspace, workspace / 'maps.json')
    assert not (workspace / 'maps.json').exists() and not list(workspace.glob('*.part'))


def test_changed_after_verify(packs, monkeypatch):
    paths, workspace, meta = packs
    def changed(p, w):
        original = meta[str(p)]
        p.write_bytes(p.read_bytes() + b'changed')
        return original
    monkeypatch.setattr(c, 'verify_pack', changed)
    with pytest.raises(ValueError, match='changed'): c.build_catalog(paths, workspace)


def test_earlier_input_changed_later(packs, monkeypatch):
    paths, workspace, meta = packs
    def changed(p, w):
        if p == paths[1]: paths[0].write_bytes(b'changed')
        return meta[str(p)]
    monkeypatch.setattr(c, 'verify_pack', changed)
    with pytest.raises(ValueError, match='previously'): c.build_catalog(paths, workspace)


def test_publish_failure_cleans_temporary(packs, monkeypatch):
    paths, workspace, _ = packs
    def failed(*args): raise OSError('No hard-link support')
    monkeypatch.setattr(c.os, 'link', failed)
    with pytest.raises(OSError): c.write_catalog(paths, workspace, workspace / 'maps.json')
    assert not (workspace / 'maps.json').exists() and not list(workspace.glob('*.part'))


def test_publish_race_preserves_other_file(packs, monkeypatch):
    paths, workspace, _ = packs
    original = c.os.link
    def race(source, target):
        Path(target).write_text('OTHER WRITER')
        return original(source, target)
    monkeypatch.setattr(c.os, 'link', race)
    out = workspace / 'maps.json'
    with pytest.raises(FileExistsError): c.write_catalog(paths, workspace, out)
    assert out.read_text() == 'OTHER WRITER' and not list(workspace.glob('*.part'))


def test_link_refusal(packs):
    paths, workspace, _ = packs
    linked = workspace / 'map.zip';linked.symlink_to(paths[0])
    with pytest.raises(ValueError): c.build_catalog([linked], workspace)
    linked_out = workspace / 'new.json';linked_out.symlink_to(workspace / 'missing.json')
    with pytest.raises(ValueError): c.write_catalog(paths, workspace, linked_out)


def test_control_filename(packs):
    _, workspace, _ = packs
    with pytest.raises(ValueError, match='Control'): c.build_catalog([workspace / 'bad\nname.zip'], workspace)


def test_wrong_input_suffix(packs):
    _, workspace, _ = packs
    with pytest.raises(ValueError, match='prepared .zip'): c.build_catalog([workspace / 'source.pbf'], workspace)


def test_cli_success_and_failure(packs, capsys):
    paths, workspace, _ = packs
    args = ['--pack', str(paths[0]), '--workspace', str(workspace), '--output', str(workspace / 'maps.json')]
    assert c.main(args) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'verified-downloads-not-installations'
    assert c.main(args) == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'failed'


def test_real_prepared_pack_catalog(tmp_path, monkeypatch):
    """Exercise the actual backend with explicitly fictional PBF data, offline."""
    pytest.importorskip('fieldforge.navigation.region_install')
    from test_usa_prepare import Reply, tiny_osm
    from tools.usa_maps import acquire, prepare
    sources = tmp_path / 'sources'; sources.mkdir()
    output = tmp_path / 'output'; output.mkdir()
    raw = tiny_osm()
    def reply(url):
        if url.endswith('.md5'):
            content = (hashlib.md5(raw).hexdigest() + '  vermont-latest.osm.pbf').encode()
        elif url.endswith('.pbf'): content = raw
        else: content = b'fictional polygon\nEND\n'
        return Reply(content, url)
    def deny(*args, **kwargs): raise AssertionError('No network')
    monkeypatch.setattr(socket, 'socket', deny)
    acquire.acquire_region(sources, 'vermont', transport=reply)
    pack, meta, _ = prepare.prepare_one(sources / 'vermont', output)
    result = c.write_catalog([pack], output, output / 'maps.json')
    assert result['packs'][0]['source_sha256'] == meta['files']['source']['sha256']
    assert result['totals']['map_features'] == 1
    assert result['packs'][0]['road_preparation']['state'] == 'not-requested'
    assert not result['packs'][0]['validated_navigation']
