import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.pathways import (
    LearningCatalog,
    LearningGoal,
    LearningProgress,
    PathwayStore,
    ProgressConflict,
    default_catalog,
)


def goal(slug, deps=(), stage=1, articles=()):
    return LearningGoal(slug, slug.title(), stage, "Test domain", "Learning objective",
                        "Safe exercise", "Test requirements", deps, articles)


@pytest.fixture
def store(tmp_path):
    return PathwayStore(KnowledgeLibrary(tmp_path / "library.db"))


def add_reading(store, slug="starter-v1-measurement"):
    store.library.upsert(KnowledgeArticle(slug, "Measurement practice", "Exact local text.", "math"))


def record(store, slug, status="practiced", note=""):
    return store.save(slug, status=status, note=note, expected_revision=store.progress(slug).revision)


def test_catalog_has_24_goals_six_stages_and_stable_dependency_order():
    catalog = default_catalog()
    assert len(catalog.goals) == 24
    assert sorted({g.stage for g in catalog.goals}) == [1, 2, 3, 4, 5, 6]
    assert [g.stage for g in catalog.goals] == sorted(g.stage for g in catalog.goals)
    for item in catalog.goals:
        plan = catalog.plan(item.slug)
        identifiers = [g.slug for g in plan]
        assert len(identifiers) == len(set(identifiers))
        assert identifiers[-1] == item.slug
        for g in plan:
            assert all(identifiers.index(dep) < identifiers.index(g.slug) for dep in g.prerequisites)
    assert catalog.plan("computing") == default_catalog().plan("computing")


def test_diamond_prerequisites_are_not_duplicated():
    catalog = LearningCatalog((goal("top", ("left", "right")), goal("right", ("base",)),
                               goal("base"), goal("left", ("base",))))
    assert [g.slug for g in catalog.plan("top")] == ["base", "left", "right", "top"]


@pytest.mark.parametrize("goals,match", [
    ((), "1 to 500"), ((goal("a"), goal("a")), "duplicate"),
    ((goal("a", ("missing",)),), "unknown"),
    ((goal("a", ("a",)),), "cycle"),
    ((goal("a", ("b",)), goal("b", ("a",))), "cycle"),
])
def test_invalid_graph_rejected(goals, match):
    with pytest.raises(ValueError, match=match):
        LearningCatalog(goals)


@pytest.mark.parametrize("change", [
    {"slug": "Bad slug"}, {"stage": True}, {"stage": 0}, {"stage": 7},
    {"title": ""}, {"exercise": "\x00"}, {"prerequisites": ("x", "x")},
    {"articles": ["x"]},
])
def test_invalid_goal_rejected(change):
    with pytest.raises(ValueError):
        replace(goal("test"), **change)


def test_initialization_is_additive_and_does_not_fill_library_or_progress(store):
    assert store.library.count() == 0
    assert len(store.views()) == 24
    assert store.progress("water") == LearningProgress()
    with store.library.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM pathway_progress").fetchone()[0] == 0
    PathwayStore(store.library)
    assert store.library.count() == 0


def test_reading_states_distinguish_missing_imports_from_missing_guides(store):
    before = {row.goal.slug: row for row in store.views()}
    assert before["measurement"].reading_state == "Intro not installed"
    assert before["computing"].reading_state == "Guide needed"
    add_reading(store)
    after = {row.goal.slug: row for row in store.views()}
    assert after["measurement"].reading_state == "Intro available"
    assert after["measurement"].installed_articles == (("starter-v1-measurement", "Measurement practice"),)
    assert store.progress("measurement").status == "not_started"


def test_unrelated_similar_title_is_not_falsely_claimed_as_linked_reading(store):
    add_reading(store, "unrelated-measurement")
    assert not store.views(content="reading_available")


def test_study_suggestions_require_all_ancestors_not_just_immediate_parents(store):
    catalog = LearningCatalog((goal("a"), goal("b", ("a",)), goal("c", ("b",), articles=("c-guide",))))
    custom = PathwayStore(store.library, catalog)
    add_reading(custom, "c-guide")
    record(custom, "b")  # Prior experience may be recorded, but it doesn't complete a.
    assert [r.goal.slug for r in custom.views(content="next")] == []
    assert custom.views()[-1].pending_prerequisites == ("a",)
    record(custom, "a")
    assert [r.goal.slug for r in custom.views(content="next")] == ["c"]
    record(custom, "a", "needs_review")
    assert not custom.views(content="next")


def test_filters_search_and_no_fake_next_steps(store):
    assert not store.views(content="next")
    add_reading(store)
    assert [r.goal.slug for r in store.views(content="next")] == ["measurement"]
    assert [r.goal.slug for r in store.views(query="CONSISTENT units")] == ["measurement"]
    assert len(store.views(stage=6)) == 4
    assert all(not r.goal.articles for r in store.views(content="guide_needed"))
    assert all(r.goal.articles and not r.installed_articles for r in store.views(content="reading_missing"))
    record(store, "measurement")
    assert not store.views(content="next")
    assert not store.views(query="nothing-matches-this")


@pytest.mark.parametrize("kwargs", [{"stage": True}, {"stage": 9}, {"query": "x" * 201},
                                     {"query": None}, {"content": "unknown"}])
def test_invalid_view_filters_raise(store, kwargs):
    with pytest.raises(ValueError):
        store.views(**kwargs)


def test_progress_survives_reopen_and_preserves_exact_notes(store):
    value = record(store, "water", "exploring", "  café — 草稿\n\n")
    assert value.revision == 1 and value.updated_at.endswith("+00:00")
    reopened = PathwayStore(KnowledgeLibrary(store.library.database_path))
    assert reopened.progress("water") == value
    assert record(reopened, "water", "exploring", value.note).revision == 1
    with store.library.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM pathway_progress").fetchone()[0] == 1


@pytest.mark.parametrize("kwargs", [
    {"status": "complete"}, {"status": []}, {"note": "\x00"}, {"note": "x" * 20001},
    {"note": None}, {"expected_revision": True}, {"expected_revision": -1}, {"slug": "not-a-goal"},
])
def test_invalid_progress_is_rejected_before_write(store, kwargs):
    args = {"slug": "water", "status": "exploring", "note": "OK", "expected_revision": 0, **kwargs}
    with pytest.raises(ValueError):
        store.save(**args)
    assert store.progress("water") == LearningProgress()


def test_stale_save_cannot_clobber_other_window(store):
    first = record(store, "water", note="First window")
    record(store, "water", note="Second window")
    with pytest.raises(ProgressConflict):
        store.save("water", status="practiced", note="Old edits", expected_revision=first.revision)
    assert store.progress("water").note == "Second window"


def test_simultaneous_first_saves_have_one_winner(store):
    def save(note):
        try:
            store.save("water", status="exploring", note=note, expected_revision=0)
            return "saved"
        except ProgressConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(save, ("A", "B"))) == ["conflict", "saved"]
    assert store.progress("water").revision == 1


def test_noop_default_does_not_create_private_records(store):
    assert record(store, "water", "not_started") == LearningProgress()
    with store.library.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM pathway_progress").fetchone()[0] == 0


def test_article_notes_and_learning_notes_are_separate(store):
    add_reading(store)
    store.library.annotate("starter-v1-measurement", bookmarked=True, note="Article note")
    record(store, "measurement", note="Different learning note")
    assert store.library.annotation("starter-v1-measurement")["note"] == "Article note"
    assert store.progress("measurement").note == "Different learning note"


def test_future_schema_fails_without_rewriting_version_or_notes(store):
    record(store, "water", note="Preserve")
    with store.library.connect() as db:
        db.execute("UPDATE knowledge_state SET value='99' WHERE key='pathways_schema'")
    with pytest.raises(ValueError, match="unsupported"):
        PathwayStore(store.library)
    assert store.progress("water").note == "Preserve"
    with store.library.connect() as db:
        assert db.execute("SELECT value FROM knowledge_state WHERE key='pathways_schema'").fetchone()[0] == "99"


def test_removed_catalog_goals_remain_stored_not_destroyed(store):
    record(store, "water", note="Previous catalog")
    subset = PathwayStore(store.library, LearningCatalog((goal("new-goal"),)))
    assert len(subset.views()) == 1
    assert PathwayStore(store.library).progress("water").note == "Previous catalog"


def test_failed_write_rolls_back_without_mutating_article_or_progress(store):
    add_reading(store)
    with store.library.connect() as db:
        db.execute("CREATE TRIGGER deny_learning BEFORE INSERT ON pathway_progress "
                   "BEGIN SELECT RAISE(ABORT, 'simulated failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="simulated"):
        record(store, "water")
    assert store.progress("water") == LearningProgress()
    assert store.library.search("local")


def test_network_not_required(store, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network attempted")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    add_reading(store)
    record(store, "measurement")
    assert len(store.views()) == 24
    assert store.catalog.plan("computing")

