"""Offline asset verifier: contract, filesystem, corruption, privacy, and CLI tests."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).parents[1] / 'fieldforge' / 'knowledge' / 'asset_audit.py'
spec = importlib.util.spec_from_file_location('fieldforge_asset_audit_under_test', MODULE)
audit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = audit
spec.loader.exec_module(audit)
CONTENT = b'Original synthetic reference.\n'
PRIVATE = b'PRIVATE FILE CONTENT MUST NOT APPEAR IN REPORTS'


def asset(path='books/reference.txt', content=CONTENT, **changes):
    row = dict(asset_id='ref-a', title='Reference A', path=path, kind='text',
               collection='Learning', bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
               source_url='https://example.org/original', license='Original synthetic fixture',
               review_status='reviewed')
    row.update(changes)
    return row


def raw(rows=None):
    return json.dumps({'schema': audit.SCHEMA, 'version': 1,
                       'assets': [asset()] if rows is None else rows}, ensure_ascii=False).encode()


def put(root, path='books/reference.txt', content=CONTENT):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def run(root, rows=None, **kwargs):
    return audit.audit_assets(root, raw(rows), **kwargs)


@pytest.fixture
def root(tmp_path):
    directory = tmp_path / 'private-root'
    directory.mkdir()
    put(directory)
    return directory


def test_verified(root):
    report = run(root)
    assert report.status == 'verified' and report.exit_code == 0
    assert report.counts['verified'] == 1
    assert report.counts['hashed_bytes'] == len(CONTENT)
    assert report.counts['verified_bytes'] == len(CONTENT)
    assert report.collections['Learning']['verified'] == 1
    assert report.manifest_sha256 == hashlib.sha256(raw()).hexdigest()


def test_same_length_tamper(root):
    put(root, content=b'X' * len(CONTENT))
    report = run(root)
    assert report.assets[0].reason == 'changed_hash'
    assert report.assets[0].observed_sha256 == hashlib.sha256(b'X' * len(CONTENT)).hexdigest()
    assert report.counts['changed'] == 1 and report.exit_code == 2
    assert report.counts['verified_bytes'] == 0


@pytest.mark.parametrize('content', [b'', b'x', CONTENT + b'added'])
def test_wrong_size_never_hashed(root, content, monkeypatch):
    put(root, content=content)
    monkeypatch.setattr(audit.os, 'read', lambda *_: pytest.fail('wrong-size file was read'))
    report = run(root)
    assert report.assets[0].reason == 'changed_size'
    assert report.assets[0].observed_bytes == len(content)
    assert report.counts['hashed_bytes'] == 0


def test_missing_and_missing_ancestor(root):
    for name in ['missing.txt', 'absent/folder/book.pdf']:
        report = run(root, [asset(path=name)])
        assert report.assets[0].status == 'missing'
        assert report.counts['verified'] == 0


def test_empty_files_are_verified(root):
    put(root, 'empty.txt', b'')
    report = run(root, [asset('empty.txt', b'')], file_budget=0, total_budget=0)
    assert report.status == 'verified'
    assert report.assets[0].observed_sha256 == hashlib.sha256(b'').hexdigest()


@pytest.mark.parametrize('budget', [0, 1, len(CONTENT)-1])
def test_file_budget_not_false_pass(root, budget):
    report = run(root, file_budget=budget)
    assert report.status == 'incomplete' and report.exit_code == 2
    assert report.counts['not_checked'] == 1
    assert report.counts['hashed_bytes'] == 0


def test_total_budget_and_later_small_asset(root):
    put(root, 'two.txt', b'12')
    put(root, 'large.txt', b'12345')
    put(root, 'one.txt', b'1')
    rows = [asset('two.txt', b'12', asset_id='two'),
            asset('large.txt', b'12345', asset_id='large'),
            asset('one.txt', b'1', asset_id='one')]
    report = run(root, rows, total_budget=3)
    assert [r.status for r in report.assets] == ['verified', 'not_checked', 'verified']
    assert report.counts['hashed_bytes'] == 3


@pytest.mark.parametrize('field', ['file_budget', 'total_budget'])
@pytest.mark.parametrize('value', [-1, True, 1.5, '1', None, 2**63])
def test_invalid_budgets(root, field, value):
    with pytest.raises(audit.AssetInputError):
        run(root, **{field: value})


def test_missing_outranks_unchecked(root):
    report = run(root, [asset(), asset('missing.txt', asset_id='missing')], total_budget=0)
    assert report.status == 'integrity_failed'
    assert report.counts['missing'] == 1 and report.counts['not_checked'] == 1


def test_metadata_separate_from_byte_integrity(root):
    report = run(root, [asset(source_url='', license='', review_status='unreviewed')])
    assert report.counts['verified'] == 1 and report.counts['metadata_gaps'] == 1
    assert report.status == 'attention_required' and report.exit_code == 1
    assert len(report.assets[0].metadata_gaps) == 3


def test_outdated_metadata(root):
    result = run(root, [asset(review_status='outdated')]).assets[0]
    assert result.status == 'verified' and result.metadata_gaps == ('Review status: outdated',)


@pytest.mark.parametrize('path', [
    '', '/', '/etc/passwd', '../private', 'a/../b', './a', 'a/./b', 'a//b', 'a/',
    '\\server\\share', 'C:/private', 'C:private', 'a\\b', 'a\x00b', 'a\nb', 'a\tb',
    'a:b', 'a*b', 'a?b', 'a"b', 'a<b', 'a>b', 'a|b', ' CON', 'CON', 'nul.txt',
    'AUX', 'COM1', 'lpt9.txt', 'COM¹.txt', 'a./b', 'a /b', 'a/ b', 'a/.. ',
    'a\u202eb', 'a\u200bb', 'é' * 128, '/'.join(['a'] * 65),
])
def test_unsafe_manifest_paths_rejected(path):
    with pytest.raises(audit.AssetInputError):
        audit.parse_manifest(raw([asset(path=path)]))


@pytest.mark.parametrize('path', ['books/test 1.txt', 'books/科学.txt', 'LPT10.txt',
                                  'COM0.txt', 'food/é.txt', '.hidden/file.json'])
def test_portable_paths(path):
    assert audit.parse_manifest(raw([asset(path=path)]))[0].path == path


@pytest.mark.parametrize('field,value', [
    ('bytes', -1), ('bytes', True), ('bytes', 1.2), ('bytes', '1'), ('bytes', 2**63),
    ('sha256', 'a'*63), ('sha256', 'A'*64), ('sha256', 'x'*64), ('sha256', None),
    ('title', ''), ('title', ' '), ('title', 123), ('title', 'a'*501), ('title', 'a\x00b'),
    ('asset_id', ' ref'), ('asset_id', 'ref '), ('asset_id', ''), ('collection', ''),
    ('kind', 'executable'), ('kind', None), ('review_status', 'certified'),
    ('source_url', 'javascript:alert(1)'), ('source_url', 'file:///private'),
    ('source_url', 'https://user:pass@example.com/a'), ('source_url', 'https://example.com:wrong'),
    ('source_url', 'https://'), ('source_url', 'https://example.com/a b'),
    ('source_url', 'https://[bad'), ('source_url', 'ftp://example.com/file'),
    ('license', 'a'*1001), ('review_status', True),
])
def test_bad_asset_fields(field, value):
    with pytest.raises(audit.AssetInputError):
        audit.parse_manifest(raw([asset(**{field: value})]))


@pytest.mark.parametrize('value', [b'', b'[]', b'null', b'{}', b'\xff',
    b'{"schema":NaN}', b'{"schema":Infinity}', b'{"schema":"a","schema":"b"}',
    b'['*1500 + b']'*1500])
def test_bad_json(value):
    with pytest.raises(audit.AssetInputError):
        audit.parse_manifest(value)


def test_manifest_size_limit(monkeypatch):
    monkeypatch.setattr(audit, 'MAX_MANIFEST_BYTES', 2)
    with pytest.raises(audit.AssetInputError):
        audit.parse_manifest(raw())


@pytest.mark.parametrize('field,value', [('version', True), ('version', 2), ('schema', 'other'),
                                         ('assets', []), ('assets', {}), ('assets', [None])])
def test_bad_manifest_envelope(field, value):
    document = json.loads(raw())
    document[field] = value
    with pytest.raises(audit.AssetInputError):
        audit.parse_manifest(json.dumps(document).encode())


@pytest.mark.parametrize('change', ['extra_top', 'extra_asset', 'missing_asset', 'surrogate'])
def test_strict_contract(change):
    document = json.loads(raw())
    if change == 'extra_top':
        document['extra'] = 1
    if change == 'extra_asset':
        document['assets'][0]['extra'] = 1
    if change == 'missing_asset':
        del document['assets'][0]['license']
    if change == 'surrogate':
        document['assets'][0]['title'] = '\ud800'
    with pytest.raises(audit.AssetInputError):
        audit.parse_manifest(json.dumps(document).encode())


@pytest.mark.parametrize('rows', [
    [asset(), asset('other.txt')],
    [asset(), asset('BOOKS/REFERENCE.TXT', asset_id='other')],
    [asset('é.txt'), asset('e\u0301.txt', asset_id='other')],
    [asset(asset_id='one'), asset('other.txt', asset_id='ONE')],
    [asset('a'), asset('a/b.txt', asset_id='other')],
])
def test_collisions(rows):
    with pytest.raises(audit.AssetInputError):
        audit.parse_manifest(raw(rows))


def test_invalid_manifest_prevents_all_asset_access(root, monkeypatch):
    monkeypatch.setattr(audit, '_hash_file', lambda *_: pytest.fail('accessed before validation'))
    with pytest.raises(audit.AssetInputError):
        run(root, [asset(), asset('../secret', asset_id='bad')])


@pytest.mark.parametrize('placement', ['leaf', 'ancestor', 'internal', 'dangling'])
def test_links_not_followed(root, tmp_path, placement):
    outside = tmp_path / 'outside'
    outside.mkdir()
    put(outside, 'reference.txt', PRIVATE)
    path = root / 'link'
    if placement == 'leaf':
        path.symlink_to(outside / 'reference.txt')
        relative = 'link'
    elif placement == 'ancestor':
        path.symlink_to(outside, target_is_directory=True)
        relative = 'link/reference.txt'
    elif placement == 'internal':
        path.symlink_to(root / 'books/reference.txt')
        relative = 'link'
    else:
        path.symlink_to(tmp_path / 'absent')
        relative = 'link'
    report = run(root, [asset(relative)])
    assert report.assets[0].status == 'unsafe'
    assert report.counts['hashed_bytes'] == 0
    assert PRIVATE.decode() not in json.dumps(report.to_dict())


def test_directory_instead_of_file(root):
    report = run(root, [asset('books')])
    assert report.assets[0].status == 'unsafe'


@pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='POSIX FIFO test')
def test_fifo_does_not_block(root):
    os.mkfifo(root / 'pipe')
    assert run(root, [asset('pipe')]).assets[0].status == 'unsafe'
    with pytest.raises(audit.AssetInputError):
        audit._read_manifest(root / 'pipe')


def test_permission_error_is_reported(root, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError()
    monkeypatch.setattr(audit.os, 'open', denied)
    report = run(root)
    assert report.assets[0].status == 'unreadable'
    assert report.counts['hashed_bytes'] == 0


def test_partial_read_consumes_budget(root, monkeypatch):
    put(root, 'one.txt', b'1')
    original_read = audit.os.read
    calls = 0
    def flaky(fd, size):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('device failed')
        return original_read(fd, min(size, 2))
    monkeypatch.setattr(audit.os, 'read', flaky)
    report = run(root, [asset(), asset('one.txt', b'1', asset_id='one')], total_budget=len(CONTENT))
    assert report.assets[0].status == 'unreadable'
    assert report.assets[0].bytes_read == 2
    assert report.assets[1].status == 'verified'
    assert report.counts['hashed_bytes'] == 3


@pytest.mark.parametrize('mutation', ['append', 'replace', 'delete', 'link'])
def test_mutation_during_read_cannot_pass(root, tmp_path, monkeypatch, mutation):
    original_read = audit.os.read
    done = False
    def changing(fd, size):
        nonlocal done
        block = original_read(fd, size)
        if not done:
            done = True
            target = root / 'books/reference.txt'
            if mutation == 'append':
                with target.open('ab') as stream: stream.write(b'extra')
            elif mutation == 'replace':
                replacement = tmp_path / 'replacement'
                replacement.write_bytes(CONTENT)
                replacement.replace(target)
            elif mutation == 'delete':
                target.unlink()
            else:
                target.unlink()
                target.symlink_to(tmp_path / 'absent')
        return block
    monkeypatch.setattr(audit.os, 'read', changing)
    report = run(root)
    assert report.assets[0].status in {'unreadable', 'unsafe'}
    assert report.counts['verified'] == 0
    assert report.counts['hashed_bytes'] == len(CONTENT)


def test_no_network_access(root, monkeypatch):
    monkeypatch.setattr(socket, 'socket', lambda *_a, **_k: pytest.fail('network requested'))
    assert run(root).status == 'verified'
    assert audit.snapshot_assets(root)


def test_snapshot_round_trip_unreviewed_and_deterministic(root):
    first = audit.snapshot_assets(root)
    assert audit.snapshot_assets(root) == first
    parsed = audit.parse_manifest(first)
    assert parsed[0].review_status == 'unreviewed'
    assert parsed[0].license == parsed[0].source_url == ''
    report = audit.audit_assets(root, first)
    assert report.counts['verified'] == 1
    assert report.status == 'attention_required'


def test_manifest_portable_across_root_move(root, tmp_path):
    manifest = audit.snapshot_assets(root)
    moved = tmp_path / 'other-machine'
    shutil.copytree(root, moved)
    assert audit.audit_assets(moved, manifest).counts['verified'] == 1


def test_snapshot_mixed_types_and_sorted_output(root):
    for name in ['video/a.mp4', 'audio/a.flac', 'maps/a.mbtiles', 'books/a.pdf',
                 'images/a.svg', 'a.txt', 'unknown.bin']:
        put(root, name, b'fixture')
    rows = audit.parse_manifest(audit.snapshot_assets(root))
    assert [row.path for row in rows] == sorted(row.path for row in rows)
    assert {row.kind for row in rows} == {'text', 'audio', 'video', 'pdf', 'image', 'data', 'other'}
    assert any(row.collection == 'Unsorted' for row in rows)


def test_snapshot_empty_rejected(tmp_path):
    with pytest.raises(audit.AssetInputError):
        audit.snapshot_assets(tmp_path)


def test_snapshot_links_abort(root):
    (root / 'link').symlink_to(root / 'books')
    with pytest.raises(audit.AssetInputError):
        audit.snapshot_assets(root)


@pytest.mark.parametrize('kwargs', [{'file_budget': 0}, {'total_budget': 0}])
def test_snapshot_budget_cannot_make_partial_manifest(root, kwargs):
    with pytest.raises(audit.AssetInputError):
        audit.snapshot_assets(root, **kwargs)


def test_snapshot_count_limit(root, monkeypatch):
    monkeypatch.setattr(audit, 'MAX_ASSETS', 1)
    put(root, 'second.txt')
    with pytest.raises(audit.AssetInputError):
        audit.snapshot_assets(root)


def test_snapshot_tree_limit(root, monkeypatch):
    monkeypatch.setattr(audit, 'MAX_TREE_ENTRIES', 1)
    with pytest.raises(audit.AssetInputError):
        audit.snapshot_assets(root)


def test_snapshot_duplicate_case_rejected(root):
    put(root, 'BOOKS/REFERENCE.TXT')
    with pytest.raises(audit.AssetInputError):
        audit.snapshot_assets(root)


def test_extra_files_not_checked(root):
    put(root, 'extra.bin', PRIVATE)
    report = run(root)
    assert report.counts['total'] == 1 and report.status == 'verified'
    assert 'extra.bin' not in audit.render_html(report)


def test_reports_omit_root_and_file_contents(root):
    put(root, content=PRIVATE)
    report = run(root, [asset(content=PRIVATE)])
    for text in [json.dumps(report.to_dict()), audit.render_html(report)]:
        assert str(root) not in text and PRIVATE.decode() not in text
        assert 'books/reference.txt' in text


def test_html_escaping_and_csp(root):
    payload = '<img src="https://example.com/private" onerror="alert(1)">'
    report = run(root, [asset(title=payload, collection=payload, license=payload)])
    document = audit.render_html(report)
    assert payload not in document
    assert '&lt;img' in document
    assert '<script src=' not in document
    assert 'Content-Security-Policy' in document
    assert "default-src 'none'" in document
    assert 'role="status"' in document


def test_aggregation(root):
    put(root, 'two.txt', b'2')
    report = run(root, [asset(), asset('two.txt', b'2', asset_id='two', collection='Other'),
                        asset('missing', asset_id='absent', collection='Other')])
    assert report.collections['Other']['verified'] == 1
    assert report.collections['Other']['missing'] == 1
    assert report.counts['verified_bytes'] == len(CONTENT) + 1


def test_missing_root(tmp_path):
    with pytest.raises(audit.AssetInputError):
        audit.audit_assets(tmp_path / 'missing', raw())


def test_file_as_root(root):
    with pytest.raises(audit.AssetInputError):
        audit.audit_assets(root / 'books/reference.txt', raw())


def test_write_new_no_clobber(tmp_path):
    destination = tmp_path / 'report.html'
    audit.write_new(destination, b'first')
    with pytest.raises(audit.AssetInputError):
        audit.write_new(destination, b'second')
    assert destination.read_bytes() == b'first'
    assert not list(tmp_path.glob('.fieldforge-*'))


def test_write_new_symlink_no_clobber(tmp_path):
    target = tmp_path / 'target'
    target.write_bytes(PRIVATE)
    destination = tmp_path / 'report'
    destination.symlink_to(target)
    with pytest.raises(audit.AssetInputError):
        audit.write_new(destination, b'new')
    assert target.read_bytes() == PRIVATE


def test_write_failure_cleans_temporary(tmp_path, monkeypatch):
    def fail(*_):
        raise OSError('no hard-link support')
    monkeypatch.setattr(audit.os, 'link', fail)
    with pytest.raises(audit.AssetInputError):
        audit.write_new(tmp_path / 'report', b'content')
    assert not list(tmp_path.iterdir())


def test_read_manifest_roundtrip(tmp_path):
    manifest = tmp_path / 'manifest.json'
    manifest.write_bytes(raw())
    assert audit._read_manifest(manifest) == raw()


def test_read_manifest_symlink_rejected(tmp_path):
    manifest = tmp_path / 'manifest.json'
    manifest.write_bytes(raw())
    alias = tmp_path / 'alias'
    alias.symlink_to(manifest)
    with pytest.raises(audit.AssetInputError):
        audit._read_manifest(alias)


def test_read_manifest_oversize(tmp_path, monkeypatch):
    manifest = tmp_path / 'manifest.json'
    manifest.write_bytes(raw())
    monkeypatch.setattr(audit, 'MAX_MANIFEST_BYTES', 5)
    with pytest.raises(audit.AssetInputError):
        audit._read_manifest(manifest)


def cli(*args):
    return subprocess.run([sys.executable, str(MODULE), *map(str, args)],
                          capture_output=True, text=True, timeout=10)


def test_cli_snapshot_and_verify(root, tmp_path):
    manifest = tmp_path / 'manifest.json'
    result = cli('snapshot', root, '--output', manifest)
    assert result.returncode == 0, result.stderr
    for format in ['html', 'json']:
        output = tmp_path / ('report.' + format)
        result = cli('verify', root, manifest, '--format', format, '--output', output)
        assert result.returncode == 1, result.stderr  # bytes match, metadata still unreviewed
        assert output.is_file() and '1/1 verified' in result.stdout


def test_cli_success_and_integrity_exit_codes(root, tmp_path):
    manifest = tmp_path / 'manifest.json'
    manifest.write_bytes(raw())
    assert cli('verify', root, manifest, '--output', tmp_path / 'pass.html').returncode == 0
    (root / 'books/reference.txt').unlink()
    assert cli('verify', root, manifest, '--output', tmp_path / 'fail.html').returncode == 2


def test_cli_no_write_inside_library(root):
    result = cli('snapshot', root, '--output', root / 'manifest.json')
    assert result.returncode == 3
    assert not (root / 'manifest.json').exists()


def test_cli_refuses_existing_output(root, tmp_path):
    output = tmp_path / 'protected'
    output.write_bytes(PRIVATE)
    result = cli('snapshot', root, '--output', output)
    assert result.returncode == 3 and output.read_bytes() == PRIVATE


def test_cli_invalid_manifest_no_output_or_private_path(root, tmp_path):
    manifest = tmp_path / 'private-manifest'
    manifest.write_bytes(b'bad')
    output = tmp_path / 'report.html'
    result = cli('verify', root, manifest, '--output', output)
    assert result.returncode == 3 and not output.exists()
    assert str(root) not in result.stderr and str(manifest) not in result.stderr


def test_cli_interrupt_no_partial_report(root, tmp_path, monkeypatch, capsys):
    manifest = tmp_path / 'manifest.json'
    manifest.write_bytes(raw())
    def interrupt(*_a, **_k):
        raise KeyboardInterrupt()
    monkeypatch.setattr(audit, 'audit_assets', interrupt)
    output = tmp_path / 'report'
    result = audit.main(['verify', str(root), str(manifest), '--output', str(output)])
    assert result == 130 and not output.exists()
    assert 'interrupted' in capsys.readouterr().err


def test_import_has_no_side_effects(tmp_path):
    result = subprocess.run([sys.executable, '-c',
        f'import runpy; runpy.run_path({str(MODULE)!r}, run_name="inspection_only")'],
        cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0 and result.stdout == ''
    assert not list(tmp_path.iterdir())
