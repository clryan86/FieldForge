"""Exercise the shipped education data through real offline install/search paths."""

import copy
import hashlib
import json
import socket
from pathlib import Path

import pytest

from fieldforge.content import install_reference_library
from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.packs import import_pack
from tools.build_education_library import (
    PREFIX,
    build,
    canonical,
    compile_lessons,
    digest,
    envelope,
)

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "fieldforge/content/packs"


def read_pack(name):
    return json.loads((PACKS / name).read_text("utf-8"))


def no_network(*args, **kwargs):
    raise AssertionError("education must install and search entirely offline")


def test_shipped_lessons_match_editable_source_and_have_complete_learning_paths():
    source = json.loads((ROOT / "fieldforge/content/education/lessons.json").read_text("utf-8"))
    articles, entries = compile_lessons(source)
    assert len(articles) == 72
    assert read_pack("education-foundations.json") == envelope(articles)
    combined = read_pack("reference-library.json")
    by_slug = {row["slug"]: row for row in combined["data"]["articles"]}
    inventory = {row["slug"]: row for row in read_pack("catalog.json")["articles"]}
    for article, entry in zip(articles, entries):
        assert by_slug[article["slug"]] == article
        assert inventory[entry["slug"]] == entry
        assert article["checksum"] == hashlib.sha256(article["body"].encode()).hexdigest()
        assert article["reviewed_on"] == ""
        assert len(article["body"].split()) >= 300
        for heading in ("LEARNING GOAL", "MATERIALS", "PRACTICE", "ANSWERS AND CHECKS",
                        "ADAPT AND CONTINUE", "BACKGROUND REFERENCES", "SOURCE AND REUSE"):
            assert heading in article["body"]
    # Exact metadata and text of every pre-expansion article, not merely its count.
    original = [row for row in combined["data"]["articles"] if not row["slug"].startswith(PREFIX)]
    assert len(original) == 267
    assert digest(original) == "954331fda1b1e03b20b5c7a1520b4a17a8fc25c167e660596b72a01c06f98e42"
    # Earlier education imports must extend without --replace or losing private notes.
    assert envelope(articles[:24])["checksum"] == (
        "f0fb92291612e3149a370add027597226dacee4b7b391b78707a46dee9c7c7c6"
    )
    assert envelope(articles[:40])["checksum"] == (
        "afba7e213110378f15c740113e4bbebe63e6f118808bbc1379764eb1db999b3d"
    )
    assert envelope(articles[:56])["checksum"] == (
        "1cf3d9bedf958cba4616ceef49be631faeb8a6fd6531cf5ede1ccf02d5037823"
    )
    assert {row["edition"] for row in entries[:24]} == {"2026-10-02"}
    assert {row["edition"] for row in entries[24:]} == {"2026-10-03"}


@pytest.mark.parametrize("use_fts", [True, False])
@pytest.mark.parametrize("previous_lessons", [0, 24, 40, 56])
def test_upgrade_preserves_existing_articles_and_notes_and_is_searchable_offline(
    tmp_path, monkeypatch, use_fts, previous_lessons
):
    monkeypatch.setattr(socket, "socket", no_network)
    all_rows = read_pack("reference-library.json")["data"]["articles"]
    old_rows = [row for row in all_rows if not row["slug"].startswith(PREFIX)
                or int(row["slug"][len(PREFIX):]) <= previous_lessons]
    old_pack = tmp_path / "old.json"
    old_pack.write_bytes(canonical(envelope(old_rows)))
    library = KnowledgeLibrary(tmp_path / "library.db", use_fts=use_fts)
    import_pack(library, old_pack)
    slug = old_rows[0]["slug"]
    original = library.get(slug)
    library.annotate(slug, bookmarked=True, note="Personal note survives the education update")
    if previous_lessons:
        library.annotate(PREFIX + f"{previous_lessons:02d}", bookmarked=True,
                         note="My teaching adaptation")
    result = install_reference_library(library)
    assert result == {"imported": 72 - previous_lessons, "unchanged": 267 + previous_lessons,
                      "annotations": 0, "packs": 1}
    assert library.count() == 339
    assert library.get(slug) == original
    assert library.annotation(slug) == {
        "bookmarked": True, "note": "Personal note survives the education update"
    }
    if previous_lessons:
        assert library.annotation(PREFIX + f"{previous_lessons:02d}") == {
            "bookmarked": True, "note": "My teaching adaptation"
        }
    assert len(library.browse(100, category="education")) == 84
    for query, expected in (("phonics", "05"), ("remainders", "14"),
                            ("percentages", "16"), ("timetable", "19"),
                            ("digraphs", "27"), ("equations", "37"),
                            ("germination", "39"), ("legend", "40"),
                            ("vowel-teams", "41"), ("required-fields", "44"),
                            ("partial-products", "48"), ("median", "51"),
                            ("probability", "52"), ("friction", "53"),
                            ("infiltration", "54"), ("corroboration", "55"),
                            ("abstention", "56"), ("diphthongs", "58"),
                            ("fluency", "59"), ("summary", "60"),
                            ("decimal-subtraction", "61"), ("decimal-division", "63"),
                            ("percentage-points", "64"), ("protractor", "65"),
                            ("circumference", "67"), ("cubic-units", "68"),
                            ("shadow", "69"), ("frequency", "70"),
                            ("decomposer", "71"), ("missing-data", "72")):
        hits = library.search(query, 100, category="education")
        assert PREFIX + expected in {hit.slug for hit in hits}
    repeat = install_reference_library(library)
    assert repeat["imported"] == 0 and repeat["unchanged"] == 339


def test_standalone_education_pack_import_and_conflict_rollback(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, "socket", no_network)
    library = KnowledgeLibrary(tmp_path / "separate.db")
    result = import_pack(library, PACKS / "education-foundations.json")
    assert result == {"imported": 72, "unchanged": 0, "annotations": 0}
    assert library.count() == 72
    other = KnowledgeLibrary(tmp_path / "conflict.db")
    slug = PREFIX + "72"
    other.upsert(KnowledgeArticle(slug, "Local lesson", "Keep my local version", "education"))
    other.annotate(slug, bookmarked=True, note="Private adaptation")
    with pytest.raises(ValueError, match="different content"):
        install_reference_library(other)
    assert other.count() == 1
    assert other.get(slug).body == "Keep my local version"
    assert other.annotation(slug)["note"] == "Private adaptation"


def test_rebuild_is_deterministic_and_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, "socket", no_network)
    for relative in ("fieldforge/content/education/lessons.json",
                     "fieldforge/content/packs/reference-library.json",
                     "fieldforge/content/packs/catalog.json"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    build(tmp_path)
    for name in ("reference-library.json", "education-foundations.json", "catalog.json"):
        assert (tmp_path / "fieldforge/content/packs" / name).read_bytes() == (PACKS / name).read_bytes()


def test_broken_prerequisites_and_missing_answers_are_rejected():
    source = json.loads((ROOT / "fieldforge/content/education/lessons.json").read_text("utf-8"))
    invalid = copy.deepcopy(source)
    invalid["lessons"][0]["prerequisites"] = ["24"]
    with pytest.raises(ValueError, match="prerequisites"):
        compile_lessons(invalid)
    invalid = copy.deepcopy(source)
    invalid["lessons"][0]["answers"] = []
    with pytest.raises(ValueError, match="answer"):
        compile_lessons(invalid)
