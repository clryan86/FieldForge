"""Original bytes are archived as data, never treated as a trusted executable PDF."""

import hashlib
import os
import socket
import sqlite3
import subprocess
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge import originals as module
from fieldforge.knowledge.originals import (
    CapturedPDF,
    OriginalConflict,
    OriginalStore,
    capture_pdf,
)


@pytest.fixture(params=[True, False], ids=["fts", "fallback"])
def store(tmp_path, request):
    library = KnowledgeLibrary(tmp_path / "library #1.db", use_fts=request.param)
    library.upsert(KnowledgeArticle("guide", "Fictional source", "Keep full original for diagrams.\n", "reference"))
    return OriginalStore(library.database_path)


def captured(value=b"%PDF-1.7\nUnparsed, deliberately incomplete example\x00\xff\r\n", filename="source.pdf"):
    return CapturedPDF(filename, value)


def save(store, *, article=False, data=None):
    return store.store(data or captured(), article=store.anchor("guide") if article else None, acknowledged=True).record


def test_no_originals_created_on_open_and_schema_is_idempotent(store):
    before = store.path.read_bytes()
    assert not store.browse().records
    assert store.browse().stored_bytes == 0
    OriginalStore(store.path)
    assert store.path.read_bytes() == before


def test_capture_preserves_exact_binary_without_path_or_pdf_parser(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("parser or viewer must not run")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(webbrowser, "open", forbidden)
    path = tmp_path / "Fictional manual.pdf"
    path.write_bytes(captured().data)
    snapshot = capture_pdf(path)
    assert snapshot.data == path.read_bytes()
    assert snapshot.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert snapshot.filename == path.name and str(path.parent) not in repr(snapshot)
    assert "Unparsed" not in repr(snapshot)
    path.write_bytes(b"Changed later")
    assert snapshot.data == captured().data


@pytest.mark.parametrize("filename,data", [("bad.txt", b"%PDF-1"), ("good.pdf", b""),
                                           ("a.pdf", b"wrong"), ("bad\n.pdf", b"%PDF-"),
                                           ("../bad.pdf", b"%PDF-"), ("x"*256+".pdf", b"%PDF-"),
                                           ("ok.pdf", bytearray(b"%PDF-1"))])
def test_invalid_capture_metadata_and_data_rejected(filename, data):
    with pytest.raises(ValueError):
        CapturedPDF(filename, data)


def test_size_limit_checked_before_read_and_missing_db_not_created(tmp_path, monkeypatch):
    path = tmp_path / "large.pdf"
    path.write_bytes(b"%PDF-" + b"a"*20)
    monkeypatch.setattr(module, "MAX_FILE_BYTES", 10)
    with pytest.raises(ValueError, match="16 MiB"):
        capture_pdf(path)
    with pytest.raises(sqlite3.OperationalError):
        OriginalStore(tmp_path / "missing.db")
    assert not (tmp_path / "missing.db").exists()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO test")
def test_nonblocking_fifo_is_not_accepted_as_file(tmp_path):
    path = tmp_path / "pipe.pdf"
    os.mkfifo(path)
    with pytest.raises(ValueError, match="regular"):
        capture_pdf(path)


def test_storage_requires_explicit_consent_and_does_not_seed_articles(store):
    before = store.path.read_bytes()
    for option in (False, 1, None, "yes"):
        with pytest.raises(ValueError, match="confirm"):
            store.store(captured(), acknowledged=option)
    assert store.path.read_bytes() == before
    result = store.store(captured(), acknowledged=True)
    assert result.added and result.record.state == "unlinked"
    assert store.read_verified(result.record) == captured().data
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM knowledge_articles").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM knowledge_annotations").fetchone()[0] == 0


def test_same_file_reuses_blob_and_duplicate_reference_does_not_rewrite_filename(store):
    first = save(store)
    before = store.path.read_bytes()
    again = store.store(captured(filename="renamed.pdf"), acknowledged=True)
    assert not again.added and again.record == first
    assert store.path.read_bytes() == before
    linked = save(store, article=True)
    snapshot = store.browse()
    assert snapshot.references == 2 and snapshot.unique_files == 1
    assert snapshot.stored_bytes == len(captured().data)
    assert linked.id != first.id and linked.article_title == "Fictional source"
    assert OriginalStore(store.path).read_verified(linked) == captured().data


def test_article_snapshot_races_and_legacy_edits_are_detected(store):
    anchor = store.anchor("guide")
    library = KnowledgeLibrary(store.path)
    library.upsert(replace(library.get("guide"), body="Different version"))
    with pytest.raises(OriginalConflict, match="changed since capture"):
        store.store(captured(), article=anchor, acknowledged=True)
    assert store.browse().references == 0
    linked = save(store, article=True)
    library.annotate("guide", bookmarked=True, note="Private annotation")
    assert store.browse().records[0].state == "current"
    library.upsert(replace(library.get("guide"), license="Different rights"))
    assert store.browse().records[0].state == "changed"
    assert store.read_verified(linked) == captured().data  # Never lose the original on article edits.
    with pytest.raises(OriginalConflict, match="earlier article version"):
        save(store, article=True)
    assert store.browse().references == 1


def test_deleted_article_does_not_delete_original_and_it_remains_exportable(store, tmp_path):
    linked = save(store, article=True)
    with store.connect() as db:
        db.execute("DELETE FROM knowledge_articles WHERE slug='guide'")
    assert store.browse().records[0].state == "missing"
    assert store.browse().records[0].article_title == linked.article_title
    exported = store.export(linked, tmp_path / "recovered.pdf", acknowledged=True)
    assert exported.path.read_bytes() == captured().data


def test_full_blob_validation_on_export_and_dedup_but_listing_is_metadata_only(store, tmp_path):
    record = save(store)
    with store.connect() as db:
        raw = b"%PDF-" + b"x"*(record.byte_count - 5)
        db.execute("UPDATE knowledge_original_blobs SET payload=?", (raw,))
    assert store.browse().references == 1  # No all-file integrity claims in a listing.
    with pytest.raises(ValueError, match="checksum failed"):
        store.read_verified(record)
    with pytest.raises(ValueError, match="checksum failed"):
        store.export(record, tmp_path / "bad.pdf", acknowledged=True)
    assert not (tmp_path / "bad.pdf").exists()
    with pytest.raises(ValueError, match="checksum failed"):
        save(store)
    assert store.remove(record) == 0  # Damaged bytes can still be deliberately removed.


def test_export_exact_bytes_without_overwriting_or_browser_calls(store, tmp_path, monkeypatch):
    record = save(store)
    def forbidden(*args, **kwargs):
        raise AssertionError("no link/viewer/network operation expected")
    monkeypatch.setattr(os, "link", forbidden)
    monkeypatch.setattr(webbrowser, "open", forbidden)
    exported = store.export(record, tmp_path / "exact.pdf", acknowledged=True)
    assert exported.path.read_bytes() == captured().data
    assert exported.sha256 == record.file_sha256
    assert exported.byte_count == len(captured().data)
    with pytest.raises(FileExistsError):
        store.export(record, exported.path, acknowledged=True)
    assert exported.path.read_bytes() == captured().data
    with pytest.raises(ValueError):
        store.export(record, tmp_path / "wrong.txt", acknowledged=True)
    with pytest.raises(ValueError):
        store.export(record, tmp_path / "unconfirmed.pdf")
    assert not (tmp_path / "unconfirmed.pdf").exists()


def test_symlink_destination_is_not_followed(store, tmp_path):
    record = save(store)
    destination = tmp_path / "alias.pdf"
    target = tmp_path / "keep.pdf"
    target.write_bytes(b"keep")
    try:
        destination.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(FileExistsError):
        store.export(record, destination, acknowledged=True)
    assert target.read_bytes() == b"keep" and destination.is_symlink()


def test_failed_export_cleans_only_new_file(store, tmp_path, monkeypatch):
    record = save(store)
    def fail(_):
        raise OSError("simulated flush failure")
    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError, match="simulated"):
        store.export(record, tmp_path / "partial.pdf", acknowledged=True)
    assert not (tmp_path / "partial.pdf").exists()
    old = tmp_path / "old.pdf"
    old.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        store.export(record, old, acknowledged=True)
    assert old.read_bytes() == b"keep"


def test_reference_removal_does_not_delete_shared_bytes_notes_or_external_file(store):
    unlinked = save(store)
    linked = save(store, article=True)
    library = KnowledgeLibrary(store.path)
    library.annotate("guide", bookmarked=True, note="PRIVATE_NOTE")
    assert store.remove(linked) == 1
    assert store.read_verified(unlinked) == captured().data
    assert library.annotation("guide")["note"] == "PRIVATE_NOTE"
    assert library.get("guide")
    assert store.remove(unlinked) == 0
    assert store.browse().unique_files == 0


def test_stale_removed_recreated_and_modified_records_are_rejected(store, tmp_path):
    old = save(store)
    store.remove(old)
    newer = save(store)
    assert newer.id > old.id
    with pytest.raises(OriginalConflict):
        store.remove(old)
    with pytest.raises(OriginalConflict):
        store.export(old, tmp_path / "stale.pdf", acknowledged=True)
    with store.connect() as db:
        db.execute("UPDATE knowledge_original_refs SET filename='changed.pdf' WHERE id=?", (newer.id,))
    with pytest.raises(OriginalConflict):
        store.read_verified(newer)
    assert store.browse().references == 1


@pytest.mark.parametrize("operation", ["insert", "delete"])
def test_transaction_failure_keeps_blob_and_references_consistent(store, operation):
    if operation == "insert":
        with store.connect() as db:
            db.execute("CREATE TRIGGER reject_reference BEFORE INSERT ON knowledge_original_refs "
                       "BEGIN SELECT RAISE(ABORT,'simulated'); END")
        with pytest.raises(sqlite3.IntegrityError):
            save(store)
        assert store.browse().unique_files == store.browse().references == 0
    else:
        record = save(store)
        with store.connect() as db:
            db.execute("CREATE TRIGGER reject_delete BEFORE DELETE ON knowledge_original_blobs "
                       "BEGIN SELECT RAISE(ABORT,'simulated'); END")
        with pytest.raises(sqlite3.IntegrityError):
            store.remove(record)
        assert store.read_verified(record) == captured().data
        assert store.browse().references == 1


def test_concurrent_duplicate_stores_produce_one_reference(store):
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: store.store(captured(), acknowledged=True), range(2)))
    assert sum(result.added for result in results) == 1
    assert results[0].record.id == results[1].record.id
    assert store.browse().unique_files == store.browse().references == 1


def test_caps_enforced_inside_transaction_and_duplicate_not_double_charged(store, monkeypatch):
    monkeypatch.setattr(module, "MAX_STORED_BYTES", len(captured().data))
    first = save(store)
    save(store, article=True)
    with pytest.raises(ValueError, match="storage limit"):
        save(store, data=captured(b"%PDF-different bytes"))
    assert store.browse().unique_files == 1
    monkeypatch.setattr(module, "MAX_RECORDS", 2)
    assert not store.store(captured(), acknowledged=True).added
    with pytest.raises(ValueError, match="reference limit"):
        save(store, data=captured(b"%PDF-another file"))
    assert store.read_verified(first)


def test_literal_search_paging_and_association_filter(store):
    for i in range(27):
        save(store, data=captured(f"%PDF-file{i}".encode(), f"Café {i:02}.pdf"))
    save(store, article=True)
    assert len(store.browse("CAFÉ", limit=25).records) == 25
    assert len(store.browse("CAFÉ", offset=25, limit=25).records) == 2
    assert len(store.browse(article_slug="guide").records) == 1
    assert not store.browse("% ' OR 1=1 --").records
    assert store.browse().references == 28


@pytest.mark.parametrize("case", ["future", "unversioned", "missing", "column"])
def test_schema_mismatches_fail_without_reset(store, case):
    with store.connect() as db:
        if case == "future":
            db.execute("UPDATE knowledge_state SET value='9' WHERE key='original_files_schema'")
        elif case == "unversioned":
            db.execute("DELETE FROM knowledge_state WHERE key='original_files_schema'")
        elif case == "missing":
            db.execute("DROP TABLE knowledge_original_refs")
        else:
            db.execute("ALTER TABLE knowledge_original_refs ADD COLUMN future TEXT")
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        OriginalStore(store.path)
    assert store.path.read_bytes() == before


def test_no_network_parser_or_execution_and_no_private_note_reads(store, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No external operations")
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    real = sqlite3.connect
    def connect(*args, **kwargs):
        db = real(*args, **kwargs)
        def authorize(action, table, column, *_):
            if table in {"knowledge_annotations", "household_members", "pathway_progress"}:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.set_authorizer(authorize)
        return db
    monkeypatch.setattr(sqlite3, "connect", connect)
    record = save(store, article=True)
    assert store.export(record, tmp_path / "offline.pdf", acknowledged=True).path.exists()


def test_invalid_filters_and_unknown_or_corrupt_articles(store):
    for options in ({"query": None}, {"limit": True}, {"offset": -1}, {"article_slug": []}, {"query": "x"*201}):
        with pytest.raises(ValueError):
            store.browse(**options)
    with pytest.raises(OriginalConflict):
        store.anchor("missing")
    with store.connect() as db:
        db.execute("UPDATE knowledge_articles SET checksum='bad' WHERE slug='guide'")
    with pytest.raises(ValueError, match="checksum"):
        store.anchor("guide")
    with pytest.raises(ValueError):
        store.read_verified(None)


def test_changed_during_capture_is_not_accepted_as_a_stable_file(tmp_path, monkeypatch):
    from types import SimpleNamespace

    path = tmp_path / "changing.pdf"
    path.write_bytes(b"%PDF-test")
    real = os.fstat
    calls = []
    def changed(fd):
        info = real(fd)
        calls.append(True)
        return info if len(calls) == 1 else SimpleNamespace(st_size=info.st_size,
               st_mtime_ns=info.st_mtime_ns+1, st_ctime_ns=info.st_ctime_ns)
    monkeypatch.setattr(os, "fstat", changed)
    with pytest.raises(ValueError, match="changed while"):
        capture_pdf(path)


def test_concurrent_capacity_checks_cannot_exceed_byte_budget(store, monkeypatch):
    monkeypatch.setattr(module, "MAX_STORED_BYTES", 10)
    def limited(index):
        try:
            store.store(captured(f"%PDF-{index}".encode()), acknowledged=True)
            return "stored"
        except ValueError as exc:
            assert "storage limit" in str(exc)
            return "limit"
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(limited, range(2))) == ["limit", "stored"]
    assert store.browse().stored_bytes == 6
