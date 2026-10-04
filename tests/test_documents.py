import hashlib
import os
import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from fieldforge.knowledge import KnowledgeLibrary
from fieldforge.knowledge import documents as module
from fieldforge.knowledge.documents import (
    DocumentConflict,
    TextDocument,
    commit_document,
    prepare_article,
    read_text_document,
)


def source(body=b"Tool ledger\n\nRecord the location of each tool.\n"):
    return TextDocument("tool_ledger.md", body)


def proposal(document=None, **kwargs):
    document = document or source()
    return prepare_article(document, **{"title": "Tool ledger", "category": "tools", **kwargs})


@pytest.fixture(params=[True, False], ids=["fts", "fallback"])
def library(tmp_path, request):
    return KnowledgeLibrary(tmp_path / "library.db", use_fts=request.param)


@pytest.mark.parametrize("suffix", [".txt", ".md", ".markdown", ".TXT", ".MD"])
def test_regular_utf8_documents_load_without_normalization(tmp_path, suffix):
    raw = "  Café 🚜\r\n\r\n測定\t2\n\n".encode()
    path = tmp_path / ("Notes" + suffix)
    path.write_bytes(raw)
    doc = read_text_document(path)
    assert doc.name == path.name
    assert doc.body == raw.decode()
    assert doc.file_sha256 == doc.body_sha256 == hashlib.sha256(raw).hexdigest()
    assert path.read_bytes() == raw


def test_optional_bom_removed_without_changing_crlf_or_whitespace():
    raw = b"\xef\xbb\xbf  Unchanged text\r\n\r\n"
    doc = source(raw)
    assert doc.body == "  Unchanged text\r\n\r\n"
    assert doc.file_sha256 != doc.body_sha256
    assert doc.body_sha256 == hashlib.sha256(doc.body.encode()).hexdigest()


@pytest.mark.parametrize("raw", [b"", b"\xef\xbb\xbf", b" \r\n\t", b"\xff\xfeX\0",
                                   b"abc\x00xyz", b"abc\x1bxyz", b"abc\x7fxyz", b"caf\xe9"])
def test_empty_non_utf8_and_binary_inputs_rejected(raw):
    with pytest.raises(ValueError):
        source(raw)


@pytest.mark.parametrize("name", ["book.pdf", "notes.docx", "image.png", "program.exe", "data.json", "no-extension"])
def test_unsupported_formats_rejected_before_open(tmp_path, name):
    with pytest.raises(ValueError, match="not supported"):
        read_text_document(tmp_path / name)


def test_missing_source_and_directory_fail_without_creating_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_text_document(tmp_path / "missing.txt")
    directory = tmp_path / "dir.txt"
    directory.mkdir()
    with pytest.raises((OSError, ValueError)):
        read_text_document(directory)
    assert not (tmp_path / "missing.txt").exists()


def test_file_byte_limit_is_enforced_before_reading(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "MAX_DOCUMENT_BYTES", 20)
    path = tmp_path / "large.txt"
    path.write_bytes(b"x" * 21)
    with pytest.raises(ValueError, match="exceeds"):
        read_text_document(path)
    with pytest.raises(ValueError, match="2 MiB"):
        source(b"x" * 21)


def test_character_limit_is_enforced_separately(monkeypatch):
    monkeypatch.setattr(module, "MAX_DOCUMENT_CHARACTERS", 10)
    with pytest.raises(ValueError, match="characters"):
        source(b"x" * 11)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX-only FIFO check")
def test_named_pipe_is_not_read_or_waited_on(tmp_path):
    path = tmp_path / "pipe.txt"
    os.mkfifo(path)
    with pytest.raises(ValueError, match="regular"):
        read_text_document(path)


def test_suggested_identity_is_body_based_not_filename_or_bom():
    first = TextDocument("one.txt", b"Same body\r\n")
    second = TextDocument("other.md", b"\xef\xbb\xbfSame body\r\n")
    assert first.suggested_id == second.suggested_id
    assert first.suggested_title == "one"
    assert source().suggested_title == "tool ledger"
    assert TextDocument("one.txt", b"Changed body").suggested_id != first.suggested_id


def test_preview_is_inert_and_does_not_execute_markdown_links(tmp_path):
    marker = tmp_path / "should-not-exist"
    doc = source(f"[link](https://example.org/)\n<script>open('{marker}', 'w')</script>".encode())
    assert "<script>" in doc.body and not marker.exists()


def test_preparing_article_does_not_invent_review_publisher_or_license():
    article = proposal()
    assert article.body == source().body
    assert article.reviewed_on == article.source_publisher == article.license == ""
    assert article.source_url == article.source_title == ""
    assert article.safety_level == "caution"


@pytest.mark.parametrize("fields", [
    {"title": ""}, {"category": " "}, {"slug": "Bad ID"}, {"slug": "../escape"},
    {"slug": "x" * 101}, {"source_url": "file:///etc/passwd"},
    {"reviewed_on": "not-a-date"}, {"safety_level": "approved"}, {"tags": "not-an-array"},
])
def test_invalid_metadata_never_reaches_import(fields):
    with pytest.raises(ValueError):
        proposal(**fields)


def test_valid_explicit_provenance_preserved(library):
    article = proposal(source_title="My document", source_publisher="Author supplied",
                       source_url="https://example.org/source", license="Reuse terms supplied by owner",
                       tags=("Tools", "local"), reviewed_on="2025-01-01")
    result = commit_document(library, article, acknowledged=True)
    assert result.status == "added" and result.slug == article.slug
    assert library.get(article.slug) == article
    assert library.search("ledger")[0].slug == article.slug


@pytest.mark.parametrize("acknowledged", [False, None, 1, "yes"])
def test_acknowledgment_required_without_implicit_consent(tmp_path, acknowledged):
    library = KnowledgeLibrary(tmp_path / "library.db")
    with pytest.raises(ValueError, match="privacy"):
        commit_document(library, proposal(), acknowledged=acknowledged)
    assert library.count() == 0


def test_import_uses_previewed_snapshot_after_source_changes(library, tmp_path):
    path = tmp_path / "selected.txt"
    path.write_bytes(b"Original text snapshot\r\n")
    doc = read_text_document(path)
    article = proposal(doc)
    path.write_bytes(b"Edited after preview")
    path.unlink()
    commit_document(library, article, acknowledged=True)
    assert library.get(article.slug).body == "Original text snapshot\r\n"


def test_repeated_identical_imports_are_noop_and_preserve_notes(library):
    article = proposal()
    commit_document(library, article, acknowledged=True)
    library.annotate(article.slug, bookmarked=True, note="Private annotation\n\n")
    before = library.database_path.read_bytes()
    assert commit_document(library, article, acknowledged=True).status == "unchanged"
    assert library.database_path.read_bytes() == before
    assert library.count() == 1
    assert library.annotation(article.slug) == {"bookmarked": True, "note": "Private annotation\n\n"}


def test_existing_text_or_metadata_never_silently_replaced(library):
    original = proposal()
    commit_document(library, original, acknowledged=True)
    library.annotate(original.slug, bookmarked=True, note="Keep my work")
    for changed in (replace(original, body="Different body"), replace(original, title="Different metadata")):
        with pytest.raises(DocumentConflict, match="Nothing was replaced"):
            commit_document(library, changed, acknowledged=True)
    assert library.get(original.slug) == original
    assert library.annotation(original.slug)["note"] == "Keep my work"


def test_corrupt_existing_checksum_is_not_silently_accepted(library):
    article = proposal()
    commit_document(library, article, acknowledged=True)
    with library.connect() as db:
        db.execute("UPDATE knowledge_articles SET checksum='bad'")
    with pytest.raises(DocumentConflict):
        commit_document(library, article, acknowledged=True)
    with library.connect() as db:
        assert db.execute("SELECT checksum FROM knowledge_articles").fetchone()[0] == "bad"


def test_deliberate_new_id_allows_a_separate_copy_without_touching_original(library):
    original = proposal()
    commit_document(library, original, acknowledged=True)
    changed = proposal(title="Another edition", slug="my-separate-copy")
    assert commit_document(library, changed, acknowledged=True).status == "added"
    assert library.count() == 2 and library.get(original.slug) == original


def test_import_does_not_store_source_path_or_input_filename(library, tmp_path):
    directory = tmp_path / "private-path-sentinel"
    directory.mkdir()
    path = directory / "private-filename-sentinel.txt"
    path.write_text("Shareable equipment ledger", encoding="utf-8")
    article = proposal(read_text_document(path), title="Public title")
    commit_document(library, article, acknowledged=True)
    with library.connect() as db:
        dump = "\n".join(db.iterdump())
    assert "private-path-sentinel" not in dump
    assert "private-filename-sentinel" not in dump


def test_two_concurrent_identical_imports_create_only_one_row(library):
    article = proposal()
    with ThreadPoolExecutor(max_workers=2) as worker:
        results = list(worker.map(lambda _: commit_document(library, article, acknowledged=True), range(2)))
    assert sorted(result.status for result in results) == ["added", "unchanged"]
    assert library.count() == 1


def test_concurrent_conflict_has_one_winner_no_overwrite(library):
    candidates = [proposal(title="First"), proposal(title="Second")]

    def save(article):
        try:
            return commit_document(library, article, acknowledged=True).status
        except DocumentConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as worker:
        results = list(worker.map(save, candidates))
    assert sorted(results) == ["added", "conflict"]
    assert library.count() == 1 and library.get(candidates[0].slug) in candidates


def test_late_write_failure_rolls_back_article_and_search(library, monkeypatch):
    original_write = library._write

    def fail(db, article):
        original_write(db, article)
        raise sqlite3.OperationalError("simulated failure after insert")

    monkeypatch.setattr(library, "_write", fail)
    with pytest.raises(sqlite3.OperationalError, match="after insert"):
        commit_document(library, proposal(), acknowledged=True)
    assert library.count() == 0 and library.search("ledger") == []


def test_no_network_apis_needed(library, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network attempted")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    path = tmp_path / "local.txt"
    path.write_bytes(b"Tool ledger")
    commit_document(library, proposal(read_text_document(path)), acknowledged=True)
    assert library.search("ledger")


def test_bad_article_type_is_rejected(library):
    with pytest.raises(ValueError, match="validated"):
        commit_document(library, {"body": "text"}, acknowledged=True)
    assert library.count() == 0
