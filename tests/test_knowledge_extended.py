import hashlib
import json
import socket
import sqlite3
from dataclasses import replace

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.__main__ import main
from fieldforge.knowledge.packs import _digest, export_pack, import_pack


@pytest.fixture
def library(tmp_path):
    return KnowledgeLibrary(tmp_path / "library.db")


@pytest.fixture
def article():
    return KnowledgeArticle("record", "Workshop Records", "  Keep a dated workshop journal.\n", "Education",
                            ("Records", "workshop"), source_title="Test fixture",
                            source_publisher="Test author", reviewed_on="2026-09-29")


def pack_file(library, article, tmp_path, *, personal=False):
    library.upsert(article)
    return export_pack(library, tmp_path / "pack.json", include_personal=personal)


def rewrite(path, change):
    payload = json.loads(path.read_text())
    change(payload)
    payload["checksum"] = _digest(payload["data"])
    path.write_text(json.dumps(payload))


def test_exact_body_checksum_and_reopen(library, article):
    library.upsert(article)
    with library.connect() as db:
        row = db.execute("SELECT body,checksum FROM knowledge_articles").fetchone()
    assert row[0] == article.body
    assert row[1] == hashlib.sha256(row[0].encode()).hexdigest()
    assert KnowledgeLibrary(library.database_path).get(article.slug) == article


def test_connections_close_and_rollback(library):
    with library.connect() as db:
        db.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        db.execute("SELECT 1")
    with pytest.raises(RuntimeError), library.connect() as db:
        db.execute("INSERT INTO knowledge_state VALUES('rollback-test','yes')")
        raise RuntimeError("simulated error")
    with library.connect() as db:
        assert db.execute("SELECT 1 FROM knowledge_state WHERE key='rollback-test'").fetchone() is None


@pytest.mark.parametrize("field,value", [
    ("title", " "), ("category", " "), ("body", ""), ("tags", "not-a-list"),
    ("tags", [None]), ("source_url", "file:///tmp/anything"), ("source_url", "javascript:alert(1)"),
    ("source_url", "https://user:password@example.org"), ("reviewed_on", "2026-02-30"),
    ("safety_level", "certified-safe"), ("body", "nul\x00text"),
])
def test_article_validation(article, field, value):
    with pytest.raises(ValueError):
        replace(article, **{field: value})


def test_filters_paging_notes_and_provenance(library, article):
    library.upsert(article)
    library.upsert(replace(article, slug="b", title="Alphabet", category="Science"))
    library.annotate(article.slug, bookmarked=True, note="Private field note.")
    assert library.categories() == ["education", "science"]
    assert library.browse(1)[0].slug == "b"
    assert library.browse(1, offset=1)[0].slug == "record"
    hits = library.search("workshop", category="EDUCATION", bookmarked=True)
    assert [x.slug for x in hits] == [article.slug]
    assert hits[0].source_publisher == "Test author"
    assert hits[0].bookmarked is True
    reopened = KnowledgeLibrary(library.database_path)
    assert reopened.annotation(article.slug) == {"bookmarked": True, "note": "Private field note."}


@pytest.mark.parametrize("query", ["  ", "!!!", '"', "*", "' OR 1=1 --"])
def test_punctuation_and_operators_are_not_executed(library, article, query):
    library.upsert(article)
    assert library.search(query) == []
    assert library.count() == 1


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": -1}, {"limit": True},
                                   {"limit": 501}, {"offset": -1}, {"offset": 1.5}])
def test_page_limits(library, kwargs):
    with pytest.raises(ValueError):
        library.browse(**kwargs)
    with pytest.raises(ValueError):
        library.search("word", **kwargs)


def test_fallback_writes_and_fts_recovery(library, article):
    library.upsert(article)
    fallback = KnowledgeLibrary(library.database_path, use_fts=False)
    assert not fallback.fts_enabled
    fallback.upsert(replace(article, body="Solar records with Unicode café.", tags=("energy",)))
    assert fallback.search("SOLAR")[0].slug == article.slug
    assert fallback.search("café")[0].slug == article.slug
    # An older FTS instance must not trust its stale index after fallback writes.
    assert library.search("solar")[0].slug == article.slug
    normal = KnowledgeLibrary(library.database_path)
    assert normal.search("solar")[0].slug == article.slug
    assert normal.search("dated") == []


def test_empty_query_and_query_limits(library):
    assert library.search("") == []
    with pytest.raises(ValueError):
        library.search("x" * 513)
    with pytest.raises(ValueError):
        library.search("word " * 33)


def test_missing_and_invalid_annotation(library, article):
    with pytest.raises(KeyError):
        library.annotation("missing")
    with pytest.raises(KeyError):
        library.annotate("missing", bookmarked=False, note="")
    library.upsert(article)
    with pytest.raises(ValueError):
        library.annotate(article.slug, bookmarked=1, note="")
    with pytest.raises(ValueError):
        library.annotate(article.slug, bookmarked=True, note="x" * 100_001)


def test_pack_round_trip_and_idempotency(library, article, tmp_path):
    path = pack_file(library, article, tmp_path)
    target = KnowledgeLibrary(tmp_path / "target.db")
    assert import_pack(target, path) == {"imported": 1, "unchanged": 0, "annotations": 0}
    assert target.get(article.slug) == article
    assert target.search("workshop")[0].slug == article.slug
    assert import_pack(target, path) == {"imported": 0, "unchanged": 1, "annotations": 0}


def test_private_notes_require_opt_in(library, article, tmp_path):
    library.upsert(article)
    library.annotate(article.slug, bookmarked=True, note="Private inventory location")
    public = export_pack(library, tmp_path / "public.json")
    assert b"Private inventory" not in public.read_bytes()
    private = export_pack(library, tmp_path / "private.json", include_personal=True)
    target = KnowledgeLibrary(tmp_path / "target.db")
    with pytest.raises(ValueError, match="private"):
        import_pack(target, private)
    assert target.count() == 0
    import_pack(target, private, restore_personal=True)
    assert target.annotation(article.slug) == library.annotation(article.slug)


def test_conflict_rolls_back_earlier_rows(library, article, tmp_path):
    library.upsert(replace(article, slug="a-first"))
    path = pack_file(library, article, tmp_path)
    target = KnowledgeLibrary(tmp_path / "target.db")
    target.upsert(replace(article, body="Existing data"))
    target.annotate(article.slug, bookmarked=True, note="Do not lose this")
    with pytest.raises(ValueError, match="already exists"):
        import_pack(target, path)
    assert target.count() == 1
    assert target.get("a-first") is None
    assert target.get(article.slug).body == "Existing data"
    import_pack(target, path, replace=True)
    assert target.get(article.slug) == article
    assert target.annotation(article.slug)["note"] == "Do not lose this"


def test_annotation_conflict_rolls_back_articles(library, article, tmp_path):
    library.upsert(article)
    library.upsert(replace(article, slug="new"))
    library.annotate(article.slug, bookmarked=False, note="Imported note")
    path = export_pack(library, tmp_path / "private.json", include_personal=True)
    target = KnowledgeLibrary(tmp_path / "target.db")
    target.upsert(article)
    target.annotate(article.slug, bookmarked=True, note="My note")
    with pytest.raises(ValueError, match="annotation already exists"):
        import_pack(target, path, restore_personal=True)
    assert target.get("new") is None
    assert target.annotation(article.slug)["note"] == "My note"


def test_sql_failure_rolls_back_whole_import(library, article, tmp_path):
    library.upsert(replace(article, slug="a-first"))
    path = pack_file(library, article, tmp_path)
    target = KnowledgeLibrary(tmp_path / "target.db")
    with target.connect() as db:
        db.execute("CREATE TRIGGER fail_import BEFORE INSERT ON knowledge_articles "
                   "WHEN new.slug='record' BEGIN SELECT RAISE(ABORT,'simulated failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        import_pack(target, path)
    assert target.count() == 0
    assert target.search("workshop") == []


def test_tampering_and_corrupted_stored_content(library, article, tmp_path):
    path = pack_file(library, article, tmp_path)
    payload = json.loads(path.read_text())
    payload["data"]["articles"][0]["source_publisher"] = "Forged publisher"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="integrity"):
        import_pack(library, path)
    with library.connect() as db:
        db.execute("UPDATE knowledge_articles SET body='corruption'")
    with pytest.raises(ValueError, match="stored content checksum"):
        export_pack(library, tmp_path / "bad.json")


@pytest.mark.parametrize("change", [
    lambda p: p.update(version=True),
    lambda p: p["data"]["articles"].append(dict(p["data"]["articles"][0])),
    lambda p: p["data"]["articles"][0].update(tags="bad"),
    lambda p: p["data"]["articles"][0].update(unknown="future field"),
    lambda p: p["data"]["articles"][0].update(body="body mismatch"),
    lambda p: p["data"]["articles"][0].update(reviewed_on="2026-00-00"),
    lambda p: p["data"].update(annotations=[{"slug": "missing", "bookmarked": True, "note": ""}]),
])
def test_invalid_records_are_rejected_before_writes(library, article, tmp_path, change):
    path = pack_file(library, article, tmp_path)
    rewrite(path, change)
    target = KnowledgeLibrary(tmp_path / "target.db")
    with pytest.raises(ValueError):
        import_pack(target, path, restore_personal=True)
    assert target.count() == 0


def test_duplicate_json_keys_and_size_bound(library, tmp_path, monkeypatch):
    path = tmp_path / "bad.json"
    path.write_text('{"format":"a","format":"b"}')
    with pytest.raises(ValueError, match="duplicate JSON key"):
        import_pack(library, path)
    monkeypatch.setattr("fieldforge.knowledge.packs.MAX_PACK_BYTES", 8)
    with pytest.raises(ValueError, match="limit"):
        import_pack(library, path)


def test_export_failure_preserves_existing_file(library, article, tmp_path, monkeypatch):
    path = pack_file(library, article, tmp_path)
    before = path.read_bytes()
    def fail(_stream):
        raise OSError("simulated disk failure")
    monkeypatch.setattr("fieldforge.knowledge.packs.os.fsync", fail)
    with pytest.raises(OSError):
        export_pack(library, path)
    assert path.read_bytes() == before
    assert list(tmp_path.glob(".fieldforge-*.tmp")) == []


def test_export_cannot_replace_database_or_hardlink(library, article, tmp_path):
    library.upsert(article)
    with pytest.raises(ValueError, match="live database"):
        export_pack(library, library.database_path)
    alias = tmp_path / "alias.json"
    alias.hardlink_to(library.database_path)
    with pytest.raises(ValueError, match="live database"):
        export_pack(library, alias)
    assert library.count() == 1


def test_cli_and_zero_network(library, article, tmp_path, monkeypatch, capsys):
    def no_network(*_args, **_kwargs):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket, "socket", no_network)
    path = pack_file(library, article, tmp_path)
    assert main(["--database", str(library.database_path), "list"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["slug"] == article.slug
    target = tmp_path / "target.db"
    assert main(["--database", str(target), "import", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["imported"] == 1
    exported = tmp_path / "out.json"
    assert main(["--database", str(target), "export", str(exported)]) == 0
    assert exported.exists()


def test_cli_reports_invalid_pack_without_traceback(library, tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("not JSON")
    with pytest.raises(SystemExit) as caught:
        main(["--database", str(library.database_path), "import", str(path)])
    assert caught.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_migration_preserves_legacy_articles_and_other_tables(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE household_sentinel(value TEXT);
            INSERT INTO household_sentinel VALUES('untouched');
            CREATE TABLE knowledge_articles (
                id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
                body TEXT NOT NULL, category TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '',
                source_title TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '',
                source_publisher TEXT NOT NULL DEFAULT '', reviewed_on TEXT NOT NULL DEFAULT '',
                safety_level TEXT NOT NULL DEFAULT 'reference', checksum TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        db.execute("INSERT INTO knowledge_articles(slug,title,body,category,checksum) VALUES(?,?,?,?,?)",
                   ("old", "Old article", "Legacy records", "education",
                    hashlib.sha256(b"Legacy records").hexdigest()))
    db.close()
    migrated = KnowledgeLibrary(path)
    assert migrated.get("old").license == ""
    assert migrated.search("legacy")[0].slug == "old"
    with migrated.connect() as db:
        assert db.execute("SELECT value FROM household_sentinel").fetchone()[0] == "untouched"


def test_export_size_is_bounded_before_replacing_file(library, article, tmp_path, monkeypatch):
    library.upsert(replace(article, body="x" * 1000))
    destination = tmp_path / "keep.json"
    destination.write_text("original")
    monkeypatch.setattr("fieldforge.knowledge.packs.MAX_PACK_BYTES", 500)
    with pytest.raises(ValueError, match="limit"):
        export_pack(library, destination)
    assert destination.read_text() == "original"
