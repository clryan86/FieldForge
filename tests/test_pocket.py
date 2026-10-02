import base64
import hashlib
import html
import re
import socket
import sqlite3
from dataclasses import replace
from html.parser import HTMLParser

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge._pocket_assets import SCRIPT, STYLE
from fieldforge.knowledge.binder import BinderEntry, FieldBinder, open_saved_binder
from fieldforge.knowledge.pocket import capture_pocket, render_pocket, save_pocket


@pytest.fixture(params=[True, False], ids=["fts", "fallback"])
def collection(tmp_path, request):
    library = KnowledgeLibrary(tmp_path / "library.db", use_fts=request.param)
    library.upsert(KnowledgeArticle("first", "Café worksheet", "Exact text\r\n\r\nEnd conditions.\n", "math"))
    library.upsert(KnowledgeArticle("second", "Second title", "Second full body.", "tools"))
    library.annotate("first", bookmarked=True, note="PRIVATE_NOTE_729")
    return library, capture_pocket(library.database_path, slugs=("first", "second"))


def test_complete_snapshots_are_readonly_and_never_include_notes(collection):
    library, captured = collection
    before = library.database_path.read_bytes()
    data = render_pocket(captured).decode()
    assert "PRIVATE_NOTE_729" not in data
    assert "End conditions." in data and "Exact text&#13;\n&#13;\n" in data
    assert "Second full body." in data and "Not supplied — verify" in data
    assert str(library.database_path) not in data
    assert before == library.database_path.read_bytes()
    assert all(entry.note is None for entry in captured.entries)


def test_later_edits_do_not_replace_the_previewed_version(collection):
    library, captured = collection
    library.upsert(replace(library.get("first"), body="Replacement version"))
    encoded = render_pocket(captured)
    assert b"Replacement version" not in encoded
    assert captured.entries[0].article.checksum.encode() in encoded


def test_capture_does_not_read_private_note_columns(collection, monkeypatch):
    library, _ = collection
    real = sqlite3.connect
    def connect(*args, **kwargs):
        db = real(*args, **kwargs)
        def authorize(action, table, column, *_):
            if action == sqlite3.SQLITE_READ and table == "knowledge_annotations" and column == "note":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.set_authorizer(authorize)
        return db
    monkeypatch.setattr(sqlite3, "connect", connect)
    assert capture_pocket(library.database_path, bookmarks=True).entries[0].note is None


def test_manual_note_smuggling_is_rejected(collection):
    _, captured = collection
    for unsafe in (replace(captured, include_notes=True),
                   replace(captured, entries=(BinderEntry(captured.entries[0].article, "private"),))):
        with pytest.raises(ValueError, match="never exports"):
            render_pocket(unsafe)


def test_csp_hashes_match_exact_script_and_style_not_unsafe_inline(collection):
    _, captured = collection
    content = render_pocket(captured).decode()
    for asset, tag in ((SCRIPT, "script"), (STYLE, "style")):
        assert re.findall(fr"<{tag}>(.*?)</{tag}>", content, re.S) == [asset]
        token = base64.b64encode(hashlib.sha256(asset.encode()).digest()).decode()
        assert html.escape("'sha256-" + token + "'", quote=True) in content
    assert "unsafe-inline" not in content and "unsafe-eval" not in content
    assert "connect-src &#x27;none&#x27;" in content


def test_all_untrusted_text_is_inert_even_in_titles_and_metadata(collection):
    _, captured = collection
    attack = '</script><script>window.PWNED=1</script><img src="https://example.invalid/leak">'
    original = captured.entries[0].article
    article = replace(original, slug='id"<x>', title=attack, body=attack, source_publisher=attack,
                      license=attack, source_url="https://example.invalid/?private=1")
    content = render_pocket(replace(captured, entries=(BinderEntry(article),), title="<em>Unsafe title</em>")).decode()
    tags, links, sources = [], [], []
    class Parser(HTMLParser):
        def handle_starttag(self, tag, attrs):
            tags.append(tag)
            for key, value in attrs:
                assert not key.startswith("on")
                if key == "href":
                    links.append(value)
                if key in ("src", "srcdoc"):
                    sources.append(value)
    Parser().feed(content)
    assert tags.count("script") == 1 and "img" not in tags and "em" not in tags
    assert not sources and all(value.startswith("#") for value in links)
    assert html.escape(attack) in content
    assert 'id="ref-1"' in content


def test_save_requires_consent_and_exclusive_new_filename(collection, tmp_path):
    _, captured = collection
    target = tmp_path / "copy.html"
    for consent in (False, None, 1, "yes"):
        with pytest.raises(ValueError, match="privacy"):
            save_pocket(captured, target, acknowledged=consent)
    assert not target.exists()
    saved = save_pocket(captured, target, acknowledged=True)
    assert target.read_bytes() == render_pocket(captured)
    assert saved.sha256 == hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        save_pocket(captured, target, acknowledged=True)
    with pytest.raises(ValueError):
        save_pocket(captured, tmp_path / "copy.db", acknowledged=True)


def test_changed_output_cannot_be_opened_through_hash_checked_action(collection, tmp_path, monkeypatch):
    _, captured = collection
    import webbrowser
    requests = []
    monkeypatch.setattr(webbrowser, "open", lambda *args, **kwargs: requests.append(args) or True)
    saved = save_pocket(captured, tmp_path / "copy.html", acknowledged=True)
    assert open_saved_binder(saved)
    saved.path.write_text("Changed", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        open_saved_binder(saved)
    assert len(requests) == 1


def test_export_makes_no_network_or_automatic_browser_request(collection, tmp_path, monkeypatch):
    _, captured = collection
    import webbrowser
    def fail(*args, **kwargs):
        raise AssertionError("external access attempted")
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, fail)
    monkeypatch.setattr(webbrowser, "open", fail)
    assert save_pocket(captured, tmp_path / "copy.html", acknowledged=True).path.exists()


def test_duplicate_empty_and_oversized_collections_do_not_render(collection, monkeypatch):
    _, captured = collection
    from fieldforge.knowledge import pocket
    with pytest.raises(ValueError):
        render_pocket(replace(captured, entries=()))
    with pytest.raises(ValueError, match="duplicate"):
        render_pocket(replace(captured, entries=(captured.entries[0], captured.entries[0])))
    monkeypatch.setattr(pocket, "MAX_TEXT_BYTES", 1)
    with pytest.raises(ValueError, match="text limit"):
        render_pocket(captured)
    with pytest.raises(ValueError):
        render_pocket(FieldBinder("test", "now", (), False))


def test_existing_capture_validation_rejects_missing_and_changed_hash(collection):
    library, _ = collection
    with pytest.raises(ValueError, match="no longer"):
        capture_pocket(library.database_path, slugs=("first", "missing"))
    with library.connect() as db:
        db.execute("UPDATE knowledge_articles SET checksum='wrong' WHERE slug='first'")
    with pytest.raises(ValueError, match="checksum mismatch"):
        capture_pocket(library.database_path, bookmarks=True)
