import json
import sqlite3

import pytest

from fieldforge.cli import main as app_main
from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary, retrieve_evidence
from fieldforge.knowledge.__main__ import main


@pytest.mark.parametrize("use_fts", [True, False])
def test_evidence_is_verbatim_and_carries_provenance(tmp_path, use_fts):
    library = KnowledgeLibrary(tmp_path / "library.db", use_fts=use_fts)
    article = KnowledgeArticle(
        "water", "Water storage", "Store potable water in clean containers. " * 15,
        "preparation", source_title="Example reference", source_publisher="Test author",
        reviewed_on="2026-09-01", safety_level="caution",
    )
    library.upsert(article)
    result = retrieve_evidence(library, "How do I store potable water?")
    assert len(result) == 1
    assert result[0].passage in article.body
    assert article.body[result[0].start_offset:result[0].end_offset] == result[0].passage
    assert result[0].checksum == article.checksum
    assert result[0].source_title == "Example reference"
    assert result[0].safety_level == "caution"
    assert retrieve_evidence(library, "unmatched") == []


def test_corrupted_content_is_not_returned(tmp_path):
    library = KnowledgeLibrary(tmp_path / "library.db")
    library.upsert(KnowledgeArticle("one", "Guide", "Original passage", "reference"))
    with sqlite3.connect(library.database_path) as db:
        db.execute("UPDATE knowledge_articles SET body='Changed passage' WHERE slug='one'")
    with pytest.raises(ValueError, match="checksum mismatch"):
        retrieve_evidence(library, "Changed passage")


def test_context_cli_is_offline_and_bounded(tmp_path, capsys, monkeypatch):
    import socket

    monkeypatch.setattr(socket, "socket", lambda *_a, **_k: pytest.fail("network access"))
    path = tmp_path / "library.db"
    KnowledgeLibrary(path).upsert(KnowledgeArticle("one", "Guide", "Offline reference", "reference"))
    assert main(["--database", str(path), "context", "offline reference"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["evidence"][0]["slug"] == "one"
    KnowledgeLibrary(path).annotate("one", bookmarked=True, note="Never export this personal note")
    assert app_main(["--database", str(path), "knowledge-context", "offline reference"]) == 0
    assert "Never export" not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--database", str(path), "context", "offline", "--limit", "21"])
