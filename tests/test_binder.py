"""Print/export snapshots are not model answers, executable content, or database backups."""

import hashlib
import os
import socket
import sqlite3
from dataclasses import replace
from html.parser import HTMLParser

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge import binder as module
from fieldforge.knowledge.binder import (
    capture_binder,
    open_saved_binder,
    render_binder,
    save_binder,
)


@pytest.fixture(params=[True, False], ids=["fts", "literal"])
def library(tmp_path, request):
    library = KnowledgeLibrary(tmp_path / "library #1.db", use_fts=request.param)
    library.upsert(KnowledgeArticle("first", "First reference", "First paragraph.\r\n\r\nDo not omit the conditions.\n\n",
                                    "reference", source_title="Fixture source", source_publisher="Fixture owner"))
    library.upsert(KnowledgeArticle("second", "Second reference", "Second full text.\n", "tools"))
    library.annotate("first", bookmarked=True, note="PRIVATE_ARTICLE_NOTE\n\n")
    return library


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.tags, self.attrs = [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.extend(attrs)


def test_capture_preserves_complete_text_order_and_default_note_privacy(library):
    before = library.database_path.read_bytes()
    captured = capture_binder(library.database_path, slugs=("second", "first"))
    assert [entry.article.slug for entry in captured.entries] == ["second", "first"]
    assert captured.entries[1].article.body == library.get("first").body
    assert all(entry.note is None for entry in captured.entries)
    rendered = render_binder(captured).decode()
    assert "PRIVATE_ARTICLE_NOTE" not in rendered
    assert "Do not omit the conditions" in rendered
    assert "&#13;" in rendered and "not independently verified" in rendered
    assert library.database_path.read_bytes() == before


def test_opted_in_notes_are_labeled_and_persist_with_snapshot(library):
    captured = capture_binder(library.database_path, slugs=("first",), include_notes=True)
    original = library.get("first")
    library.upsert(replace(original, body="New article version"))
    library.annotate("first", bookmarked=False, note="Changed note")
    assert captured.entries[0].article == original
    assert captured.entries[0].note == "PRIVATE_ARTICLE_NOTE\n\n"
    rendered = render_binder(captured).decode()
    assert "PRIVATE ARTICLE NOTES INCLUDED" in rendered
    assert "PRIVATE_ARTICLE_NOTE" in rendered and "Changed note" not in rendered
    assert original.checksum in rendered


def test_bookmarks_span_library_not_page_or_filter(library):
    library.annotate("second", bookmarked=True, note="Another note")
    captured = capture_binder(library.database_path, bookmarks=True)
    assert [entry.article.slug for entry in captured.entries] == ["first", "second"]
    library.annotate("first", bookmarked=False, note="")
    library.annotate("second", bookmarked=False, note="")
    with pytest.raises(ValueError, match="No bookmarked"):
        capture_binder(library.database_path, bookmarks=True)


def test_too_many_bookmarks_fails_instead_of_silently_truncating(library, monkeypatch):
    library.annotate("second", bookmarked=True, note="")
    monkeypatch.setattr(module, "MAX_ARTICLES", 1)
    with pytest.raises(ValueError, match="More than"):
        capture_binder(library.database_path, bookmarks=True)


@pytest.mark.parametrize("options", [
    {}, {"slugs": ()}, {"slugs": ["first"]}, {"slugs": ("first", "first")},
    {"slugs": ("first",), "bookmarks": True}, {"bookmarks": 1},
    {"slugs": (None,)}, {"slugs": ("\x00",)}, {"slugs": ("x"*201,)},
    {"slugs": ("first",), "include_notes": 1}, {"slugs": ("first",), "title": " "},
    {"slugs": ("first",), "title": "line\nline"}, {"slugs": ("first",), "title": "a"*201},
])
def test_invalid_selection_and_options_before_database_access(tmp_path, options):
    with pytest.raises(ValueError):
        capture_binder(tmp_path / "missing.db", **options)
    assert not (tmp_path / "missing.db").exists()


def test_missing_article_aborts_entire_snapshot(library):
    with pytest.raises(ValueError, match="no longer installed"):
        capture_binder(library.database_path, slugs=("first", "missing"))
    assert library.count() == 2


def test_corrupt_hash_is_not_printed_as_valid_source(library):
    with library.connect() as db:
        db.execute("UPDATE knowledge_articles SET checksum='bad' WHERE slug='second'")
    with pytest.raises(ValueError, match="checksum mismatch"):
        capture_binder(library.database_path, slugs=("first", "second"))


def test_size_caps_apply_to_whole_articles_and_optional_notes(library, monkeypatch):
    first = library.get("first")
    monkeypatch.setattr(module, "MAX_TEXT_BYTES", len(first.body.encode()))
    assert capture_binder(library.database_path, slugs=("first",))
    with pytest.raises(ValueError, match="text limit"):
        capture_binder(library.database_path, slugs=("first",), include_notes=True)
    with pytest.raises(ValueError, match="text limit"):
        capture_binder(library.database_path, slugs=("first", "second"))


def test_html_and_source_url_are_escaped_inert_text(library):
    payload = '</div><script>window.pwned=true</script><img src="https://evil.invalid/leak">'
    article = KnowledgeArticle("evil\"<id>", "Title " + payload, payload + "\n& literal entity &#13;", "test",
                               source_title=payload, source_url="https://example.org/?a=1&b=2",
                               source_publisher=payload, license=payload)
    library.upsert(article)
    library.annotate(article.slug, bookmarked=False, note=payload)
    captured = capture_binder(library.database_path, slugs=(article.slug,), title="<b>Binder</b>", include_notes=True)
    rendered = render_binder(captured).decode()
    parsed = Tags(rendered)
    assert not {"script", "img", "iframe", "object", "link", "form", "base"}.intersection(parsed.tags)
    assert all(value.startswith("#article-") for key, value in parsed.attrs if key == "href")
    assert not any(key.startswith("on") or key in {"src", "srcdoc", "ping"} for key, _ in parsed.attrs)
    assert "&lt;script&gt;" in rendered and "&lt;b&gt;Binder&lt;/b&gt;" in rendered
    assert "Content-Security-Policy" in rendered and "@media print" in rendered
    assert "&amp;#13;" in rendered


def test_default_capture_does_not_even_read_annotation_note_column(library, monkeypatch):
    real_connect = sqlite3.connect
    def connect(*args, **kwargs):
        db = real_connect(*args, **kwargs)
        def authorize(action, table, column, _database, _trigger):
            if action == sqlite3.SQLITE_READ and table == "knowledge_annotations" and column == "note":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.set_authorizer(authorize)
        return db
    monkeypatch.setattr(module.sqlite3, "connect", connect)
    assert capture_binder(library.database_path, bookmarks=True).entries[0].note is None
    with pytest.raises(sqlite3.DatabaseError):
        capture_binder(library.database_path, bookmarks=True, include_notes=True)


def test_private_record_tables_never_read(library, monkeypatch):
    with library.connect() as db:
        for table in ("household_members", "pathway_progress", "emergency_incidents"):
            db.execute(f"CREATE TABLE {table}(note TEXT)")
            db.execute(f"INSERT INTO {table} VALUES('SECRET_OTHER_RECORD')")
    encoded = render_binder(capture_binder(library.database_path, bookmarks=True, include_notes=True))
    assert b"SECRET_OTHER_RECORD" not in encoded


def test_capture_is_one_database_snapshot_even_when_another_writer_commits(library, monkeypatch):
    with library.connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
    original = KnowledgeLibrary._article
    calls = []
    def build(row):
        article = original(row)
        calls.append(article.slug)
        if len(calls) == 1:
            library.upsert(replace(library.get("second"), body="Concurrent replacement"))
        return article
    monkeypatch.setattr(KnowledgeLibrary, "_article", staticmethod(build))
    captured = capture_binder(library.database_path, slugs=("first", "second"))
    assert captured.entries[1].article.body == "Second full text.\n"


def test_save_exclusively_creates_new_html_and_never_prints_or_launches(library, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected browser launch")
    monkeypatch.setattr(module.webbrowser, "open", forbidden)
    binder = capture_binder(library.database_path, bookmarks=True)
    saved = save_binder(binder, tmp_path / "binder.html", acknowledged=True)
    assert saved.path.read_bytes() == render_binder(binder)
    assert saved.sha256 == hashlib.sha256(saved.path.read_bytes()).hexdigest()
    assert saved.bytes_written == saved.path.stat().st_size
    with pytest.raises(FileExistsError):
        save_binder(binder, saved.path, acknowledged=True)
    assert saved.path.read_bytes() == render_binder(binder)


@pytest.mark.parametrize("acknowledged", [False, None, 1, "yes"])
def test_export_requires_explicit_privacy_permission(library, tmp_path, acknowledged):
    binder = capture_binder(library.database_path, bookmarks=True)
    with pytest.raises(ValueError, match="privacy"):
        save_binder(binder, tmp_path / "blocked.html", acknowledged=acknowledged)
    assert not (tmp_path / "blocked.html").exists()


def test_destination_extension_and_existing_database_are_protected(library):
    binder = capture_binder(library.database_path, bookmarks=True)
    before = library.database_path.read_bytes()
    with pytest.raises(ValueError, match="html"):
        save_binder(binder, library.database_path, acknowledged=True)
    assert before == library.database_path.read_bytes()


def test_failed_write_removes_only_new_partial_copy(library, tmp_path, monkeypatch):
    binder = capture_binder(library.database_path, bookmarks=True)
    def fail(_):
        raise OSError("Simulated failed flush")
    monkeypatch.setattr(module.os, "fsync", fail)
    target = tmp_path / "partial.html"
    with pytest.raises(OSError, match="flush"):
        save_binder(binder, target, acknowledged=True)
    assert not target.exists()
    existing = tmp_path / "existing.html"
    existing.write_bytes(b"Do not erase")
    with pytest.raises(FileExistsError):
        save_binder(binder, existing, acknowledged=True)
    assert existing.read_bytes() == b"Do not erase"


def test_save_does_not_require_hardlinks(library, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("hard links are not needed")
    monkeypatch.setattr(os, "link", fail)
    assert save_binder(capture_binder(library.database_path, bookmarks=True),
                       tmp_path / "portable.html", acknowledged=True).path.exists()


def test_changed_saved_file_is_not_opened(library, tmp_path, monkeypatch):
    saved = save_binder(capture_binder(library.database_path, bookmarks=True), tmp_path / "binder.html", acknowledged=True)
    requests = []
    monkeypatch.setattr(module.webbrowser, "open", lambda *args, **kwargs: requests.append((args, kwargs)) or True)
    assert open_saved_binder(saved) is True
    assert requests[0][0] == (saved.path.as_uri(),)
    saved.path.write_text("<script>changed</script>", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        open_saved_binder(saved)
    assert len(requests) == 1


def test_snapshot_and_export_do_not_make_network_calls(library, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("network attempted")
    for name in ("socket", "getaddrinfo", "create_connection"):
        monkeypatch.setattr(socket, name, fail)
    assert save_binder(capture_binder(library.database_path, bookmarks=True),
                       tmp_path / "offline.html", acknowledged=True).path.exists()


def test_manually_smuggled_note_without_optin_is_rejected(library):
    binder = capture_binder(library.database_path, bookmarks=True, include_notes=True)
    with pytest.raises(ValueError, match="opt-in"):
        render_binder(replace(binder, include_notes=False))


def test_no_database_path_in_saved_document(library):
    encoded = render_binder(capture_binder(library.database_path, bookmarks=True))
    assert str(library.database_path).encode() not in encoded
    assert b"library #1.db" not in encoded
