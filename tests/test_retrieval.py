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


def test_best_passage_can_be_late_in_a_long_article(tmp_path):
    library = KnowledgeLibrary(tmp_path / "library.db")
    body = ("alpha " + "filler " * 80) * 25 + "\nalpha beta gamma: the relevant section."
    library.upsert(KnowledgeArticle("long", "Long article", body, "reference"))
    result = retrieve_evidence(library, "alpha beta gamma", passage_chars=120)[0]
    assert "beta gamma" in result.passage
    assert result.start_offset > 10_000
    assert body[result.start_offset:result.end_offset] == result.passage


def test_long_unbroken_text_cannot_exceed_the_passage_budget(tmp_path):
    library = KnowledgeLibrary(tmp_path / "library.db")
    body = "alpha " + "x" * 10_000
    library.upsert(KnowledgeArticle("long", "Long token", body, "reference"))
    result = retrieve_evidence(library, "alpha", passage_chars=120)[0]
    assert len(result.passage) <= 120
    assert body[result.start_offset:result.end_offset] == result.passage


def test_question_does_not_drop_terms_after_the_twelfth(tmp_path):
    library = KnowledgeLibrary(tmp_path / "library.db")
    library.upsert(KnowledgeArticle("last", "Last term", "Zebras are striped.", "reference"))
    question = "amber blue cedar delta elm fern green hazel iris jade kelp lemon zebras"
    assert retrieve_evidence(library, question)[0].slug == "last"
