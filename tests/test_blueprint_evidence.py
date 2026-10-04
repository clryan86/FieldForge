import json
import sqlite3
from pathlib import Path

import pytest

from fieldforge.blueprints.__main__ import main
from fieldforge.blueprints.engine import BlueprintRequest
from fieldforge.blueprints.evidence import passages, queries_for, retrieve_blueprint_evidence
from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.local_model import GenerationCancelled


@pytest.mark.parametrize("use_fts", [True, False])
def test_two_distant_passages_in_one_article_cover_distinct_request_fields(tmp_path, use_fts):
    library = KnowledgeLibrary(tmp_path / "library.db")
    body = "Battery capacity is recorded in watt hours.\n\n" + "Unrelated filler. " * 500 + "\n\nTimber joints require connection details."
    library.upsert(KnowledgeArticle("manual", "Manual", body, "reference"))
    library.annotate("manual", bookmarked=True, note="PRIVATE battery timber NOTE")
    result = retrieve_blueprint_evidence(library, BlueprintRequest(
        "engineering", "Describe the prototype.", constraints="battery capacity", resources="timber joints"), use_fts=use_fts)
    assert len(result["sources"]) == 2
    assert any("Battery capacity" in row["passage"] for row in result["sources"])
    assert any("Timber joints" in row["passage"] for row in result["sources"])
    assert "brief" in result["unmatched_fields"]
    assert "PRIVATE" not in json.dumps(result)
    for row in result["sources"]:
        assert body[row["start_offset"]:row["end_offset"]] == row["passage"]
        assert len(row["passage"]) <= 1100


@pytest.mark.parametrize("use_fts", [True, False])
def test_rare_terms_outrank_repetitive_generic_matches(tmp_path, use_fts):
    library = KnowledgeLibrary(tmp_path / "library.db")
    for i in range(25):
        library.upsert(KnowledgeArticle(f"generic-{i}", "Inventory", ("Inventory items recorded. " * 100) + str(i), "reference"))
    library.upsert(KnowledgeArticle("specific", "Metal", "Zirconium material inventory certificate.", "reference"))
    result = retrieve_blueprint_evidence(library, BlueprintRequest("engineering", "Zirconium inventory."), use_fts=use_fts)
    assert result["sources"][0]["slug"] == "specific"


@pytest.mark.parametrize("use_fts", [True, False])
def test_duplicate_passages_and_title_only_hits_do_not_fill_context(tmp_path, use_fts):
    library = KnowledgeLibrary(tmp_path / "library.db")
    for i in range(12):
        library.upsert(KnowledgeArticle(f"copy-{i}", "Copied manual", "Battery capacity reference text.", "reference"))
    library.upsert(KnowledgeArticle("title-only", "Battery capacity", "Completely unrelated information.", "reference"))
    result = retrieve_blueprint_evidence(library, BlueprintRequest("engineering", "Battery capacity."), use_fts=use_fts)
    assert len(result["sources"]) == 1
    assert result["sources"][0]["slug"] != "title-only"


def test_unicode_and_word_forms_preserve_original_offsets(tmp_path):
    library = KnowledgeLibrary(tmp_path / "library.db")
    body = "Préface — Café tools cut boards. " + "Notes. " * 250
    article = KnowledgeArticle("unicode", "Workshop", body, "reference", license="Fixture", source_publisher="Test")
    library.upsert(article)
    request = BlueprintRequest("engineering", "Café cutting boards.")
    result = retrieve_blueprint_evidence(library, request)
    assert result["sources"] and "Porter" in result["method"]
    source = result["sources"][0]
    assert source["checksum"] == article.checksum
    assert source["source_publisher"] == "Test" and source["license"] == "Fixture"
    assert body[source["start_offset"]:source["end_offset"]] == source["passage"]
    assert retrieve_blueprint_evidence(library, BlueprintRequest("engineering", "Cutting cutting."))["sources"]
    assert not retrieve_blueprint_evidence(library, BlueprintRequest("engineering", "Cutting cutting."), use_fts=False)["sources"]


def test_chunking_is_bounded_and_covers_unbroken_and_paragraph_text():
    for body in ("x" * 20_000, "An introduction.\n\n" + "meaningful text " * 500, "🙂" * 3000):
        rows = list(passages(body))
        assert rows[0][0] == 0 and rows[-1][1] == len(body)
        assert all(0 < len(text) <= 1100 and body[start:end] == text for start, end, text in rows)
        assert all(rows[i][0] <= rows[i - 1][1] for i in range(1, len(rows)))
    with pytest.raises(ValueError):
        list(passages("text", overlap=1000))


def test_query_budget_keeps_tail_and_reports_truncation():
    request = BlueprintRequest("engineering", " ".join(f"word{i}" for i in range(120)) + " zirconium")
    queries, truncated, empty = queries_for(request)
    assert truncated == ["brief"] and not empty
    assert "zirconium" in queries[-1]["terms"]
    assert sum(len(query["terms"]) for query in queries) == 96
    assert all(len(query["terms"]) <= 24 for query in queries)


def test_no_network_no_schema_mutations_and_no_evidence_for_unmatched_query(tmp_path, monkeypatch):
    import socket

    library = KnowledgeLibrary(tmp_path / "library.db")
    library.upsert(KnowledgeArticle("one", "Guide", "Workshop inventory.", "reference"))
    with library.connect() as db:
        before = list(db.execute("SELECT sql FROM sqlite_master ORDER BY name"))
    monkeypatch.setattr(socket, "socket", lambda *a, **kw: pytest.fail("Network access"))
    result = retrieve_blueprint_evidence(library, BlueprintRequest("project", "Quuxunobtainium zzznonexistent."))
    assert result["sources"] == [] and result["unmatched_fields"] == ["brief"]
    with library.connect() as db:
        assert list(db.execute("SELECT sql FROM sqlite_master ORDER BY name")) == before


def test_snapshot_is_consistent_across_concurrent_content_update(tmp_path):
    library = KnowledgeLibrary(tmp_path / "library.db")
    with library.connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
    library.upsert(KnowledgeArticle("a", "First", "Battery capacity.", "reference"))
    original = KnowledgeArticle("b", "Second", "Timber joints original details.", "reference")
    library.upsert(original)
    updated = False

    def checkpoint(message):
        nonlocal updated
        if message == "Indexing local source passages" and not updated:
            updated = True
            library.upsert(KnowledgeArticle("b", "Second", "Timber joints changed details.", "reference"))

    result = retrieve_blueprint_evidence(library, BlueprintRequest("engineering", "Battery timber joints."), checkpoint=checkpoint)
    second = next(s for s in result["sources"] if s["slug"] == "b")
    assert second["checksum"] == original.checksum and "original" in second["passage"]
    assert "changed" in library.get("b").body


def test_corruption_size_limits_and_cancellation_abort_without_partial_evidence(tmp_path, monkeypatch):
    library = KnowledgeLibrary(tmp_path / "library.db")
    library.upsert(KnowledgeArticle("one", "Guide", "Battery capacity.", "reference"))
    request = BlueprintRequest("engineering", "Battery capacity.")

    def cancelled(_message):
        raise GenerationCancelled("Cancelled")

    with pytest.raises(GenerationCancelled):
        retrieve_blueprint_evidence(library, request, checkpoint=cancelled)
    monkeypatch.setattr("fieldforge.blueprints.evidence.MAX_BYTES", 1)
    with pytest.raises(ValueError, match="32 MiB"):
        retrieve_blueprint_evidence(library, request)
    monkeypatch.undo()
    with sqlite3.connect(library.database_path) as db:
        db.execute("UPDATE knowledge_articles SET body='Battery changed' WHERE slug='one'")
    with pytest.raises(ValueError, match="checksum mismatch"):
        retrieve_blueprint_evidence(library, request)


def test_cli_evidence_works_without_model(tmp_path, capsys):
    path = tmp_path / "library.db"
    library = KnowledgeLibrary(path)
    library.upsert(KnowledgeArticle("one", "Guide", "Battery capacity.", "reference"))
    assert main(["--database", str(path), "evidence", "engineering", "Battery capacity."]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["sources"][0]["slug"] == "one"


@pytest.mark.parametrize("use_fts,minimum_found", [(True, 13), (False, 12)])
def test_bundled_retrieval_regression_targets(tmp_path, use_fts, minimum_found):
    from fieldforge.content import install_reference_library

    library = KnowledgeLibrary(tmp_path / "bundled.db")
    install_reference_library(library)
    suite = json.loads((Path(__file__).parents[1] / "tools" / "blueprint_retrieval_cases.json").read_text())
    found, total = 0, 0
    for case in suite["cases"]:
        result = retrieve_blueprint_evidence(library, BlueprintRequest(**case["request"]), use_fts=use_fts)
        if not case["expected"]:
            assert not result["sources"], case["id"]
        for expected in case["expected"]:
            total += 1
            assert expected["contains"] in library.get(expected["slug"]).body
            found += any(row["slug"] == expected["slug"] and expected["contains"] in row["passage"] for row in result["sources"])
        for row in result["sources"]:
            article = library.get(row["slug"])
            assert article.body[row["start_offset"]:row["end_offset"]] == row["passage"]
    assert total == 13 and found >= minimum_found
