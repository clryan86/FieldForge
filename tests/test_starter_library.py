import json
import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from fieldforge.knowledge import KnowledgeLibrary
from fieldforge.knowledge.packs import import_pack
from fieldforge.knowledge.starter import (
    NOTICE,
    STARTER_ARTICLE_COUNT,
    export_starter,
    install_starter,
    main,
    starter_articles,
)


def test_bundle_is_populated_validated_and_honestly_labeled():
    articles = starter_articles()
    assert len(articles) == STARTER_ARTICLE_COUNT == 12
    assert len({article.slug for article in articles}) == 12
    assert len({article.category for article in articles}) == 9
    for article in articles:
        assert article.body.startswith(NOTICE)
        assert len(article.body.split()) >= 150
        assert not article.reviewed_on  # Consultation is NOT independent expert review.
        assert article.license and article.source_publisher
        assert "starter" in article.tags
        if article.source_url:
            assert "Source consulted: 2026-10-01" in article.body
            assert "has not reviewed or endorsed" in article.body


@pytest.mark.parametrize("fts", [True, False])
@pytest.mark.parametrize("query", ["water", "generator", "compost", "measurement", "maintenance"])
def test_install_is_searchable_with_and_without_fts(tmp_path, fts, query):
    library = KnowledgeLibrary(tmp_path / "library.db", use_fts=fts)
    assert install_starter(library) == {"added": 12, "unchanged": 0, "preserved": 0}
    assert library.search(query)
    assert len(library.browse()) == 12


def test_repeat_install_preserves_edits_notes_and_bookmarks(tmp_path):
    library = KnowledgeLibrary(tmp_path / "library.db")
    install_starter(library)
    article = starter_articles()[0]
    edited = replace(article, body="My own version of the article.")
    library.upsert(edited)
    library.annotate(article.slug, bookmarked=True, note="  Private observations\n\n")
    assert install_starter(library) == {"added": 0, "unchanged": 11, "preserved": 1}
    assert library.get(article.slug) == edited
    assert library.annotation(article.slug) == {
        "bookmarked": True, "note": "  Private observations\n\n"
    }


def test_late_database_error_rolls_back_entire_install(tmp_path, monkeypatch):
    library = KnowledgeLibrary(tmp_path / "library.db")
    write = library._write
    calls = 0

    def fail_late(db, article):
        nonlocal calls
        calls += 1
        if calls == 5:
            raise sqlite3.OperationalError("simulated disk error")
        write(db, article)

    monkeypatch.setattr(library, "_write", fail_late)
    with pytest.raises(sqlite3.OperationalError, match="simulated"):
        install_starter(library)
    assert library.count() == 0
    assert library.search("water") == []


def test_concurrent_loads_are_idempotent(tmp_path):
    library = KnowledgeLibrary(tmp_path / "library.db")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: install_starter(library), range(2)))
    assert sorted(result["added"] for result in results) == [0, 12]
    assert library.count() == 12


def test_pack_is_deterministic_and_accepted_by_existing_importer(tmp_path):
    first = export_starter(tmp_path / "first.json")
    second = export_starter(tmp_path / "second.json")
    assert first.read_bytes() == second.read_bytes()
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["data"]["annotations"] == []
    library = KnowledgeLibrary(tmp_path / "existing-reader.db")
    assert import_pack(library, first) == {"imported": 12, "unchanged": 0, "annotations": 0}
    assert import_pack(library, first) == {"imported": 0, "unchanged": 12, "annotations": 0}
    assert {article.slug for article in starter_articles()} == {
        row.slug for row in library.browse()
    }


def test_operations_do_not_need_network(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network operation attempted")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    library = KnowledgeLibrary(tmp_path / "offline.db")
    install_starter(library)
    pack = export_starter(tmp_path / "offline.json")
    assert import_pack(library, pack)["unchanged"] == 12
    assert library.search("water")


def test_cli_install_and_export_do_not_export_user_notes(tmp_path, capsys):
    database = tmp_path / "personal.db"
    assert main(["--database", str(database), "install"]) == 0
    assert json.loads(capsys.readouterr().out)["added"] == 12
    library = KnowledgeLibrary(database)
    library.annotate(starter_articles()[0].slug, bookmarked=True, note="SECRET_MARKER")
    before = database.read_bytes()
    pack = tmp_path / "share.json"
    assert main(["--database", str(database), "export", str(pack)]) == 0
    assert "SECRET_MARKER" not in pack.read_text(encoding="utf-8")
    assert database.read_bytes() == before
    assert Path(json.loads(capsys.readouterr().out)["path"]) == pack
