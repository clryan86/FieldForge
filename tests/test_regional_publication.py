"""Regional preparation/import preserve new-file publication on both platforms."""

from __future__ import annotations

import errno
import hashlib
import os
import socket
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_osm_source import fixture

from fieldforge.navigation import regional_index as regional


@pytest.fixture(params=('prepare', 'import'))
def job(tmp_path, request):
    source = tmp_path / 'source.osm.pbf'
    source.write_bytes(fixture())
    target = tmp_path / 'installed.ffmap'
    inputs = [source]
    expected = None
    if request.param == 'import':
        original = regional.prepare_index(source, tmp_path / 'original.ffmap')
        expected = original.path.read_bytes()
        archive = tmp_path / 'region.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr('region/map.ffmap', expected)
            package.writestr('README.txt', 'Synthetic regression data only.')
        inputs.extend((original.path, archive))

        def run():
            return regional.import_archive(archive, target)
    else:
        def run():
            return regional.prepare_index(source, target)

    return SimpleNamespace(root=tmp_path, target=target, run=run, expected=expected,
                           source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                           inputs={path: path.read_bytes() for path in inputs})


@pytest.fixture(params=('posix', 'nt'))
def publication_api(monkeypatch, request):
    """Isolate platform behavior without changing os.name for Python or SQLite.

    On Windows use the actual non-overwriting rename. On POSIX emulate its
    new-name/moved-source semantics with a real link and unlink; the production
    Windows branch is forbidden from calling its own hard-link API.
    """
    api = SimpleNamespace(**vars(os))
    api.name = request.param
    calls = []

    def link(source, target):
        if api.name != 'posix':
            pytest.fail('Windows regional publication requested a hard link')
        calls.append(('link', Path(source), Path(target)))
        return os.link(source, target)

    def rename(source, target):
        if api.name != 'nt':
            pytest.fail('POSIX regional publication requested an overwriting rename')
        calls.append(('rename', Path(source), Path(target)))
        if os.name == 'nt':
            return os.rename(source, target)
        os.link(source, target)
        os.unlink(source)

    api.link, api.rename = link, rename
    monkeypatch.setattr(regional, 'os', api)
    return SimpleNamespace(api=api, calls=calls, operation='rename' if api.name == 'nt' else 'link')


def assert_inputs_unchanged(job):
    for path, original in job.inputs.items():
        assert path.read_bytes() == original


def assert_usable(index, job):
    assert index.path == job.target.absolute()
    reopened = regional.inspect_index(job.target)
    assert reopened.metadata == index.metadata
    assert reopened.metadata['source_sha256'] == job.source_sha256
    assert {feature.id for feature in regional.search_index(reopened, 'Map Street').features} == {
        'node/1', 'way/10',
    }
    if job.expected is not None:
        assert job.target.read_bytes() == job.expected


def test_complete_index_uses_platform_publication_and_opens_without_its_sources(
    job, publication_api, monkeypatch,
):
    before = set(job.root.iterdir())
    result = job.run()
    assert [(operation, target) for operation, _source, target in publication_api.calls] == [
        (publication_api.operation, job.target),
    ]
    assert all(not source.exists() for _operation, source, _target in publication_api.calls)
    assert set(job.root.iterdir()) == before | {job.target}
    assert_inputs_unchanged(job)
    for path in job.inputs:
        path.unlink()
    monkeypatch.setattr(socket, 'create_connection',
                        lambda *_args, **_kwargs: pytest.fail('Offline regional search requested a connection'))
    assert_usable(result, job)


@pytest.mark.parametrize('kind', ('file', 'directory'))
def test_existing_destination_is_preserved_before_preparation(job, publication_api, kind):
    if kind == 'directory':
        job.target.mkdir()
        protected = job.target / 'unrelated.txt'
    else:
        protected = job.target
    protected.write_bytes(b'Existing user data')
    before = set(job.root.iterdir())
    with pytest.raises(FileExistsError):
        job.run()
    assert protected.read_bytes() == b'Existing user data'
    assert not publication_api.calls
    assert set(job.root.iterdir()) == before
    assert_inputs_unchanged(job)


@pytest.mark.parametrize('kind', ('file', 'directory'))
def test_competing_destination_survives_atomic_publication_failure(
    job, publication_api, monkeypatch, kind,
):
    before = set(job.root.iterdir())
    original = getattr(publication_api.api, publication_api.operation)
    protected = job.target if kind == 'file' else job.target / 'unrelated.txt'

    def competitor(source, target):
        assert Path(target) == job.target
        if kind == 'directory':
            job.target.mkdir()
        protected.write_bytes(b'Concurrent owner')
        return original(source, target)

    monkeypatch.setattr(publication_api.api, publication_api.operation, competitor)
    # Windows can report access denied when the competing target is a directory.
    with pytest.raises(FileExistsError if kind == 'file' else OSError):
        job.run()
    assert protected.read_bytes() == b'Concurrent owner'
    assert set(job.root.iterdir()) == before | {job.target}
    assert_inputs_unchanged(job)


@pytest.mark.parametrize('failure', ('unsupported', 'interrupt'))
def test_failed_or_interrupted_publication_removes_private_temporaries(
    job, publication_api, monkeypatch, failure,
):
    before = set(job.root.iterdir())
    error = (OSError(errno.ENOTSUP, 'Filesystem operation unavailable') if failure == 'unsupported'
             else KeyboardInterrupt('Interrupted before publication'))

    def failed(source, target):
        assert Path(target) == job.target
        # Both paths reach publication only after creating a complete index.
        regional.inspect_index(source)
        raise error

    monkeypatch.setattr(publication_api.api, publication_api.operation, failed)
    with pytest.raises(type(error)):
        job.run()
    assert not job.target.exists()
    assert set(job.root.iterdir()) == before
    assert_inputs_unchanged(job)
