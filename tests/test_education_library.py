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
    assert len(articles) == 172
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
    assert envelope(articles[:72])["checksum"] == (
        "ae373d82e1fdcfc32ecf7ca47905a32e154ce85ea39f921596106837acb0923f"
    )
    assert envelope(articles[:88])["checksum"] == (
        "9399ab828eca803b49fe6206626dc5861e5c350d905b2975383e45814fdc9ba6"
    )
    assert envelope(articles[:100])["checksum"] == (
        "096ba6a1128a1a48fef500b7f490b3f3cb4f2f2bd66e8fb8386763e393a09770"
    )
    assert envelope(articles[:112])["checksum"] == (
        "d47f8c482e291dca8b7f5363848cd1094e1119b32067cae25c637bc0429f5f9c"
    )
    assert envelope(articles[:124])["checksum"] == (
        "dadca46e2d13720c205bc7d4bb1124e5bbde49e881121ce00171798bb60bca57"
    )
    assert envelope(articles[:136])["checksum"] == (
        "9d6d2d7081e90e53ed4db9517fd26c7c82cd7dab9a9c81bfa1c86df833c39f8a"
    )
    assert envelope(articles[:148])["checksum"] == (
        "b78249716f2a1a6e1695778c1b5892d910c38f15edb356e11924cacb493511b1"
    )
    assert envelope(articles[:160])["checksum"] == (
        "85786852c43da576f1887070bd3302e828a1ce518ff94243306b36c848bf58be"
    )
    assert {row["edition"] for row in entries[:24]} == {"2026-10-02"}
    assert {row["edition"] for row in entries[24:148]} == {"2026-10-03"}
    assert {row["edition"] for row in entries[148:]} == {"2026-10-04"}


@pytest.mark.parametrize("use_fts", [True, False])
@pytest.mark.parametrize("previous_lessons", [0, 24, 40, 56, 72, 88, 100, 112, 124, 136, 148, 160])
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
    assert result == {"imported": 172 - previous_lessons, "unchanged": 267 + previous_lessons,
                      "annotations": 0, "packs": 1}
    assert library.count() == 439
    assert library.get(slug) == original
    assert library.annotation(slug) == {
        "bookmarked": True, "note": "Personal note survives the education update"
    }
    if previous_lessons:
        assert library.annotation(PREFIX + f"{previous_lessons:02d}") == {
            "bookmarked": True, "note": "My teaching adaptation"
        }
    first_page = library.browse(100, category="education")
    second_page = library.browse(100, offset=100, category="education")
    assert len(first_page) == 100 and len(second_page) == 84
    expected_slugs = {row["slug"] for row in all_rows if row["category"] == "education"}
    assert {row.slug for row in first_page + second_page} == expected_slugs
    assert library.browse(100, offset=200, category="education") == []
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
                            ("decomposer", "71"), ("missing-data", "72"),
                            ("suffix-spelling", "73"), ("apostrophe", "74"),
                            ("subject-verb-agreement", "75"), ("clauses", "76"),
                            ("confirmation", "77"), ("discrepancy", "78"),
                            ("extended-reading", "79"), ("criteria", "80"),
                            ("order-of-operations", "81"), ("shortage", "82"),
                            ("quadrants", "83"), ("y-intercept", "84"),
                            ("translation", "85"), ("prime-factorization", "86"),
                            ("selection-bias", "87"), ("zero-baseline", "88"),
                            ("context-clues", "89"), ("reader-feedback", "90"),
                            ("changed-plan", "91"), ("paraphrase", "92"),
                            ("two-step-equations", "93"), ("inequalities", "94"),
                            ("square-roots", "95"), ("dimensional-reasoning", "96"),
                            ("file-extension", "97"), ("restore-check", "98"),
                            ("trace-table", "99"), ("capstone", "100"),
                            ("repeatability", "101"), ("thermal-energy", "102"),
                            ("mass-per-volume", "103"), ("dissolved-substance", "104"),
                            ("energy-accounting", "105"), ("dormancy", "106"),
                            ("scale-drawing", "107"), ("offcuts", "108"),
                            ("task-dependencies", "109"), ("acceptance-criteria", "110"),
                            ("wrong-field", "111"), ("read-back", "112"),
                            ("sediment-budget", "113"), ("lithification", "114"),
                            ("catchment", "115"), ("axial-tilt", "116"),
                            ("contour-interval", "117"), ("coordinate-order", "118"),
                            ("sampling-plan", "119"), ("dot-display", "120"),
                            ("paired-data", "121"), ("random-assignment", "122"),
                            ("raw-records", "123"), ("investigation-report", "124"),
                            ("net-force", "125"), ("mechanical-advantage", "126"),
                            ("average-pressure", "127"), ("heat-transfer-modes", "128"),
                            ("series-current", "129"), ("magnetic-poles", "130"),
                            ("xylem", "131"), ("plant-respiration", "132"),
                            ("habitat-factors", "133"), ("pollination-stages", "134"),
                            ("population-balance", "135"), ("nutrient-cycling", "136"),
                            ("pooled-rate", "137"), ("fixed-plus-variable", "138"),
                            ("inverse-variation", "139"), ("feasible-plan", "140"),
                            ("simultaneous-equations", "141"), ("rounding-interval", "142"),
                            ("weighted-mean", "143"), ("conditional-denominator", "144"),
                            ("successive-percentages", "145"), ("specification-reading", "146"),
                            ("requirement-levels", "147"), ("model-based-plan", "148"),
                            ("technical-word-context", "149"), ("branching-process", "150"),
                            ("diagram-legend", "151"), ("scientific-referents", "152"),
                            ("matched-comparison", "153"), ("claim-evidence-mechanism", "154"),
                            ("text-table-consistency", "155"), ("interpolation", "156"),
                            ("claim-qualifiers", "157"), ("figure-text-description", "158"),
                            ("explanation-revision", "159"), ("scientific-reading-brief", "160"),
                            ("mixed-review-record", "161"), ("timetable-inference", "162"),
                            ("request-record-review", "163"), ("remainder-choice-review", "164"),
                            ("same-whole-review", "165"), ("quantity-choice-review", "166"),
                            ("midnight-rate-review", "167"), ("distribution-review", "168"),
                            ("unequal-sample-review", "169"), ("algorithm-boundary-review", "170"),
                            ("model-error-review", "171"), ("cumulative-transfer-plan", "172")):
        hits = library.search(query, 500, category="education")
        assert PREFIX + expected in {hit.slug for hit in hits}
    repeat = install_reference_library(library)
    assert repeat["imported"] == 0 and repeat["unchanged"] == 439


def test_standalone_education_pack_import_and_conflict_rollback(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, "socket", no_network)
    library = KnowledgeLibrary(tmp_path / "separate.db")
    result = import_pack(library, PACKS / "education-foundations.json")
    assert result == {"imported": 172, "unchanged": 0, "annotations": 0}
    assert library.count() == 172
    other = KnowledgeLibrary(tmp_path / "conflict.db")
    slug = PREFIX + "172"
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
