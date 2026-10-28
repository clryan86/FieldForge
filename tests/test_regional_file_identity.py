"""Regional sources keep identity checks across Windows path/handle clocks."""

import errno
import hashlib
import os
import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_osm_source import fixture

from fieldforge.navigation import pbf_stream, regional_index


def changed_stat(info, **changes):
    fields = {name: getattr(info, name) for name in (
        'st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
    return SimpleNamespace(**(fields | changes))


@pytest.fixture
def file_access(monkeypatch):
    """Use real descriptors while isolating injected failures from other code."""
    api = SimpleNamespace(**vars(os))
    descriptors = []

    def tracked_open(*args, **kwargs):
        descriptor = os.open(*args, **kwargs)
        descriptors.append(descriptor)
        return descriptor

    api.open = tracked_open
    monkeypatch.setattr(pbf_stream, 'os', api)
    return api, descriptors


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'source.osm.pbf'
    path.write_bytes(fixture())
    return path


def assert_closed(descriptors):
    assert descriptors, 'The operation must have opened a real descriptor.'
    for descriptor in descriptors:
        try:
            os.fstat(descriptor)
        except OSError as exc:
            assert exc.errno == errno.EBADF
        else:
            os.close(descriptor)
            pytest.fail('The source descriptor was not closed.')


@pytest.mark.parametrize('offset', (-1_000_000_000, 1_000_000_000))
def test_checked_open_accepts_distinct_path_and_handle_ctime(source, file_access, offset):
    api, descriptors = file_access
    before = pbf_stream.signature(source)
    expected = source.read_bytes()
    api.fstat = lambda fd: changed_stat(os.fstat(fd), st_ctime_ns=before[4] + offset)

    stream, fingerprint = pbf_stream.checked_open(source)
    with stream:
        assert fingerprint == before
        assert stream.read() == expected
    assert pbf_stream.signature(source) == before
    assert_closed(descriptors)


@pytest.mark.parametrize('field', ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_mode'))
def test_checked_open_rejects_other_path_handle_mismatches(source, file_access, field):
    api, descriptors = file_access

    def different_handle(descriptor):
        info = os.fstat(descriptor)
        value = stat.S_IFDIR | 0o700 if field == 'st_mode' else getattr(info, field) + 1
        return changed_stat(info, **{field: value})

    api.fstat = different_handle
    with pytest.raises(ValueError, match='changed while opening'):
        pbf_stream.checked_open(source)
    assert_closed(descriptors)


def test_checked_open_rejects_real_replacement_with_same_size_and_mtime(source, file_access):
    api, descriptors = file_access
    before = source.stat()
    replacement = source.with_name('replacement.pbf')
    replacement.write_bytes(b'x' * before.st_size)
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    real_open = api.open

    def replace_before_open(*args, **kwargs):
        replacement.replace(source)
        return real_open(*args, **kwargs)

    api.open = replace_before_open
    with pytest.raises(ValueError, match='changed while opening'):
        pbf_stream.checked_open(source)
    assert source.stat().st_size == before.st_size
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    assert source.read_bytes() == b'x' * before.st_size
    assert_closed(descriptors)


@pytest.mark.parametrize('change', ('size', 'mtime'))
def test_checked_open_rechecks_real_path_changes_after_fstat(source, file_access, change):
    api, descriptors = file_access
    before = source.stat()

    def change_after_fstat(descriptor):
        info = os.fstat(descriptor)
        if change == 'size':
            with source.open('ab') as writer:
                writer.write(b'changed')
        else:
            os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))
        return info

    api.fstat = change_after_fstat
    with pytest.raises(ValueError, match='changed while opening'):
        pbf_stream.checked_open(source)
    assert_closed(descriptors)


def test_checked_open_rechecks_full_path_ctime(source, file_access, monkeypatch):
    _api, descriptors = file_access
    real_lstat = Path.lstat
    calls = 0

    def changed_path(path):
        nonlocal calls
        info = real_lstat(path)
        if path == source:
            calls += 1
            if calls > 1:
                return changed_stat(info, st_ctime_ns=info.st_ctime_ns + 1)
        return info

    monkeypatch.setattr(Path, 'lstat', changed_path)
    with pytest.raises(ValueError, match='changed while opening'):
        pbf_stream.checked_open(source)
    assert calls == 2
    assert_closed(descriptors)


@pytest.mark.parametrize('stage', ('fstat', 'path_recheck', 'fdopen'))
def test_checked_open_closes_descriptor_when_setup_is_interrupted(
    source, file_access, monkeypatch, stage
):
    api, descriptors = file_access

    class OpenInterrupted(BaseException):
        pass

    def fail(*_args, **_kwargs):
        raise OpenInterrupted(stage)

    if stage == 'path_recheck':
        real_signature = pbf_stream.signature
        calls = 0

        def interrupted_recheck(path):
            nonlocal calls
            calls += 1
            return real_signature(path) if calls == 1 else fail()

        monkeypatch.setattr(pbf_stream, 'signature', interrupted_recheck)
    else:
        setattr(api, stage, fail)
    with pytest.raises(OpenInterrupted, match=stage):
        pbf_stream.checked_open(source)
    assert_closed(descriptors)


def test_prepare_and_archive_import_allow_distinct_handle_ctime(source, file_access, tmp_path):
    api, descriptors = file_access
    api.fstat = lambda fd: changed_stat(os.fstat(fd), st_ctime_ns=0)
    raw = source.read_bytes()
    prepared = regional_index.prepare_index(source, tmp_path / 'prepared.ffmap')
    archive = tmp_path / 'regional.zip'
    with zipfile.ZipFile(archive, 'w') as package:
        package.write(prepared.path, 'region/map.ffmap')
    imported = regional_index.import_archive(archive, tmp_path / 'imported.ffmap')

    assert imported.path.read_bytes() == prepared.path.read_bytes()
    assert imported.metadata == prepared.metadata
    assert imported.metadata['source_sha256'] == hashlib.sha256(raw).hexdigest()
    assert regional_index.search_index(imported, 'Map Street').features
    assert source.read_bytes() == raw
    assert not list(tmp_path.glob('.fieldforge-index-*'))
    assert_closed(descriptors)


@pytest.mark.parametrize('reader', ('pbf', 'archive'))
def test_full_path_ctime_is_still_checked_after_reading(
    source, file_access, monkeypatch, tmp_path, reader
):
    _api, descriptors = file_access
    target = tmp_path / 'imported.ffmap'
    path = source
    if reader == 'archive':
        prepared = regional_index.prepare_index(source, tmp_path / 'prepared.ffmap')
        path = tmp_path / 'regional.zip'
        with zipfile.ZipFile(path, 'w') as package:
            package.write(prepared.path, 'map.ffmap')
        descriptors.clear()
    raw = path.read_bytes()
    real_lstat = Path.lstat
    reading = False

    def progress(current, _total):
        nonlocal reading
        reading = reading or current > 0

    def changed_path(current):
        info = real_lstat(current)
        if current == path and reading:
            return changed_stat(info, st_ctime_ns=info.st_ctime_ns + 1)
        return info

    monkeypatch.setattr(Path, 'lstat', changed_path)
    with pytest.raises(ValueError, match='changed'):
        if reader == 'pbf':
            stream = pbf_stream.PBFStream(path, progress=progress)
            list(stream)
        else:
            regional_index.import_archive(path, target, progress=progress)
    assert reading
    if reader == 'pbf':
        assert stream.receipt is None
    assert path.read_bytes() == raw
    assert not target.exists()
    assert not list(tmp_path.glob('.fieldforge-index-*'))
    assert_closed(descriptors)
