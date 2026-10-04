import json
import os
import sqlite3
import zipfile
from contextlib import closing

import pytest

from fieldforge.core import snapshot
from fieldforge.knowledge import KnowledgeLibrary
from fieldforge.knowledge.starter import install_starter, starter_articles


def seeded(path):
    library = KnowledgeLibrary(path)
    install_starter(library)
    library.annotate(starter_articles()[0].slug, bookmarked=True, note="Private snapshot note")
    with library.connect() as db:
        db.execute("CREATE TABLE incident_entries(id INTEGER PRIMARY KEY, message TEXT)")
        db.execute("INSERT INTO incident_entries VALUES(1, 'Recorded event')")
    return library


def rewrite(original, output, *, manifest_change=None, manifest_text=None, extra=None):
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(output, "w") as archive:
        manifest = json.loads(source.read("manifest.json"))
        if manifest_change:
            manifest_change(manifest)
        archive.writestr("manifest.json", manifest_text or json.dumps(manifest))
        archive.writestr("fieldforge.sqlite3", source.read("fieldforge.sqlite3"))
        if extra:
            archive.writestr(extra, "not allowed")
    return output


def test_roundtrip_includes_search_notes_and_other_tables(tmp_path):
    seeded(tmp_path / "source.db")
    pack = snapshot.export_snapshot(tmp_path / "source.db", tmp_path / "snapshot.ffbackup")
    target = tmp_path / "target.db"
    snapshot.restore_snapshot(pack, target)
    library = KnowledgeLibrary(target)
    assert library.count() == 12
    assert library.search("water")
    assert library.annotation(starter_articles()[0].slug)["note"] == "Private snapshot note"
    with library.connect() as db:
        assert db.execute("SELECT message FROM incident_entries").fetchone()[0] == "Recorded event"


def test_all_handles_close_before_files_are_published(tmp_path, monkeypatch):
    seeded(tmp_path / "source.db")
    connections = []
    original = sqlite3.connect

    class Tracked(sqlite3.Connection):
        closed = False

        def close(self):
            self.closed = True
            return super().close()

    def track(*args, **kwargs):
        kwargs["factory"] = Tracked
        connection = original(*args, **kwargs)
        connections.append(connection)  # Keep refs so GC cannot hide leaked handles.
        return connection

    monkeypatch.setattr(snapshot.sqlite3, "connect", track)
    pack = snapshot.export_snapshot(tmp_path / "source.db", tmp_path / "snapshot.ffbackup")
    assert connections and all(connection.closed for connection in connections)
    snapshot.restore_snapshot(pack, tmp_path / "target.db")
    assert all(connection.closed for connection in connections)


def test_export_includes_uncheckpointed_committed_wal(tmp_path):
    source = tmp_path / "source.db"
    seeded(source)
    with closing(sqlite3.connect(source)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("INSERT INTO incident_entries VALUES(2, 'Committed in WAL')")
        writer.commit()
        assert (tmp_path / "source.db-wal").exists()
        pack = snapshot.export_snapshot(source, tmp_path / "snapshot.ffbackup")
    snapshot.restore_snapshot(pack, tmp_path / "target.db")
    with closing(sqlite3.connect(tmp_path / "target.db")) as target:
        assert target.execute("SELECT count(*) FROM incident_entries").fetchone()[0] == 2


def test_explicit_overwrite_uses_sqlite_transaction_with_wal_target(tmp_path):
    seeded(tmp_path / "source.db")
    pack = snapshot.export_snapshot(tmp_path / "source.db", tmp_path / "snapshot.ffbackup")
    target = tmp_path / "target.db"
    with closing(sqlite3.connect(target)) as observer:
        observer.execute("PRAGMA journal_mode=WAL")
        observer.execute("CREATE TABLE old_data(value TEXT)")
        observer.execute("INSERT INTO old_data VALUES('old')")
        observer.commit()
        inode = target.stat().st_ino
        snapshot.restore_snapshot(pack, target, overwrite=True)
        assert target.stat().st_ino == inode  # Never replace a live SQLite inode.
        assert observer.execute("SELECT count(*) FROM knowledge_articles").fetchone()[0] == 12
        assert observer.execute("SELECT name FROM sqlite_master WHERE name='old_data'").fetchone() is None


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_export_cannot_overwrite_database_or_sidecars(tmp_path, suffix):
    source = tmp_path / "source.db"
    seeded(source)
    with pytest.raises(ValueError, match="live database"):
        snapshot.export_snapshot(source, tmp_path / ("source.db" + suffix))


def test_export_blocks_hardlink_alias(tmp_path):
    source = tmp_path / "source.db"
    seeded(source)
    alias = tmp_path / "alias.ffbackup"
    os.link(source, alias)
    with pytest.raises(ValueError, match="live database"):
        snapshot.export_snapshot(source, alias)
    assert KnowledgeLibrary(source).count() == 12


@pytest.mark.parametrize("kind", ["oversized", "duplicate-key", "boolean-version", "extra-member"])
def test_invalid_manifest_and_archive_rejected_early(tmp_path, kind):
    seeded(tmp_path / "source.db")
    pack = snapshot.export_snapshot(tmp_path / "source.db", tmp_path / "snapshot.ffbackup")
    changes = {}
    if kind == "oversized":
        changes["manifest_text"] = " " * (snapshot._MAX_MANIFEST_BYTES + 1)
    elif kind == "duplicate-key":
        with zipfile.ZipFile(pack) as archive:
            text = archive.read("manifest.json").decode()
        changes["manifest_text"] = '{"version":1,' + text[1:]
    elif kind == "boolean-version":
        changes["manifest_change"] = lambda manifest: manifest.update(version=True)
    else:
        changes["extra"] = "../escape"
    bad = rewrite(pack, tmp_path / "bad.ffbackup", **changes)
    with pytest.raises(ValueError):
        snapshot.restore_snapshot(bad, tmp_path / "target.db")
    assert not (tmp_path / "target.db").exists()
    assert not list(tmp_path.glob(".fieldforge-restore-*"))


def test_failed_stream_removes_partial_temporary_file(tmp_path, monkeypatch):
    seeded(tmp_path / "source.db")
    pack = snapshot.export_snapshot(tmp_path / "source.db", tmp_path / "snapshot.ffbackup")
    original = zipfile.ZipFile.open

    class Broken:
        first = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            if self.first:
                self.first = False
                return b"partial"
            raise OSError("simulated read failure")

    def open_member(self, member, *args, **kwargs):
        return Broken() if member == "fieldforge.sqlite3" else original(self, member, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", open_member)
    with pytest.raises(OSError, match="simulated"):
        snapshot.restore_snapshot(pack, tmp_path / "target.db")
    assert not list(tmp_path.glob(".fieldforge-restore-*"))
    assert not (tmp_path / "target.db").exists()


def test_non_overwrite_publish_is_race_safe(tmp_path, monkeypatch):
    seeded(tmp_path / "source.db")
    pack = snapshot.export_snapshot(tmp_path / "source.db", tmp_path / "snapshot.ffbackup")
    target = tmp_path / "target.db"
    original = os.link

    def race(source, destination):
        destination.write_bytes(b"Another process created this")
        return original(source, destination)

    monkeypatch.setattr(snapshot.os, "link", race)
    with pytest.raises(FileExistsError):
        snapshot.restore_snapshot(pack, target)
    assert target.read_bytes() == b"Another process created this"
    assert not list(tmp_path.glob(".fieldforge-restore-*"))


def test_validation_failure_does_not_touch_overwrite_target(tmp_path):
    seeded(tmp_path / "source.db")
    pack = snapshot.export_snapshot(tmp_path / "source.db", tmp_path / "snapshot.ffbackup")
    bad = rewrite(pack, tmp_path / "bad.ffbackup",
                  manifest_change=lambda manifest: manifest.update(database_sha256="0" * 64))
    target = tmp_path / "target.db"
    target.write_bytes(b"Do not change")
    with pytest.raises(ValueError, match="integrity"):
        snapshot.restore_snapshot(bad, target, overwrite=True)
    assert target.read_bytes() == b"Do not change"


def test_restore_never_overwrites_archive_itself(tmp_path):
    seeded(tmp_path / "source.db")
    pack = snapshot.export_snapshot(tmp_path / "source.db", tmp_path / "snapshot.ffbackup")
    before = pack.read_bytes()
    with pytest.raises(ValueError, match="archive"):
        snapshot.restore_snapshot(pack, pack, overwrite=True)
    assert pack.read_bytes() == before
