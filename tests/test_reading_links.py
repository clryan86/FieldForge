import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge import reading_links as module
from fieldforge.knowledge.pathways import LearningCatalog, LearningGoal, PathwayStore
from fieldforge.knowledge.reading_links import ReadingConflict


@pytest.fixture(params=[True, False], ids=["fts", "fallback"])
def store(tmp_path, request):
    library = KnowledgeLibrary(tmp_path / "library #1.db", use_fts=request.param)
    library.upsert(KnowledgeArticle("my-guide", "My measurement worksheet", "Measure the sample table.\n\n", "math",
                                   source_title="Original exercise", source_publisher="Fixture author"))
    return PathwayStore(library)


def attach(store, goal="measurement", slug="my-guide"):
    preview = store.reading_links.preview(slug)
    return store.reading_links.link(goal, slug, expected_version=preview.version)


def view(store, goal="measurement"):
    return next(row for row in store.views() if row.goal.slug == goal)


def test_initialization_is_additive_and_does_not_create_links_or_practice(store):
    assert not store.reading_links.list("measurement")
    assert store.progress("measurement").revision == 0
    assert store.library.count() == 1
    before = store.library.database_path.read_bytes()
    PathwayStore(store.library)
    assert store.library.database_path.read_bytes() == before


def test_personal_link_connects_installed_article_without_claiming_practice(store):
    linked = attach(store)
    assert linked.state == "current" and linked.revision == 1
    result = view(store)
    assert result.installed_articles == (("my-guide", "My measurement worksheet"),)
    assert result.reading_state == "User reading linked"
    assert result.next_to_explore
    assert result.progress.status == "not_started"
    assert store.reading_links.open_link(linked.id, expected_revision=1) == store.library.get("my-guide")
    assert view(store, "crops").reading_state == "Guide needed"


def test_identical_link_is_noop_and_same_article_can_serve_other_goal(store):
    linked = attach(store)
    before = store.library.database_path.read_bytes()
    assert attach(store) == linked
    assert before == store.library.database_path.read_bytes()
    other = attach(store, "construction")
    assert other.id != linked.id
    assert store.library.count() == 1


def test_builtin_starter_mapping_is_not_duplicated(store):
    article = replace(store.library.get("my-guide"), slug="starter-v1-measurement")
    store.library.upsert(article)
    with pytest.raises(ValueError, match="built-in"):
        attach(store, slug=article.slug)
    assert not store.reading_links.list("measurement")
    assert view(store).reading_state == "Intro available"


@pytest.mark.parametrize("changes", [{"body": "Different content"}, {"title": "New title"},
                                    {"source_publisher": "New publisher"}, {"reviewed_on": "2025-01-01"},
                                    {"license": "Different rights"}, {"category": "tools"}, {"tags": ("new",)},
                                    {"source_url": "https://example.org/reference"}, {"safety_level": "high_stakes"}])
def test_content_and_provenance_changes_require_explicit_relink(store, changes):
    linked = attach(store)
    old = store.library.get("my-guide")
    store.library.upsert(replace(old, **changes))
    result = view(store)
    assert result.reading_state == "Check reading links"
    assert not result.installed_articles and not result.next_to_explore
    assert result.user_links[0].state == "changed"
    assert "measurement" in [row.goal.slug for row in store.views(content="reading_missing")]
    with pytest.raises(ReadingConflict, match="source changed"):
        store.reading_links.open_link(linked.id, expected_revision=1)
    with pytest.raises(ReadingConflict, match="different source version"):
        attach(store)
    preview = store.reading_links.preview("my-guide")
    updated = store.reading_links.update(linked.id, expected_revision=1, expected_version=preview.version)
    assert updated.revision == 2 and updated.state == "current"
    assert store.progress("measurement").status == "not_started"


def test_annotation_or_storage_timestamp_does_not_invalidate_link(store):
    linked = attach(store)
    store.library.annotate("my-guide", bookmarked=True, note="Private notes\n\n")
    store.library.upsert(store.library.get("my-guide"))
    assert store.reading_links.list("measurement") == (linked,)
    assert "Private notes" not in str(store.reading_links.preview("my-guide"))


def test_preview_race_rejected_before_link_or_refresh(store):
    preview = store.reading_links.preview("my-guide")
    store.library.upsert(replace(preview.article, body="Changed after preview"))
    with pytest.raises(ReadingConflict, match="changed since preview"):
        store.reading_links.link("measurement", "my-guide", expected_version=preview.version)
    assert not store.reading_links.list("measurement")
    linked = attach(store)
    old_version = store.reading_links.preview("my-guide").version
    store.library.upsert(replace(preview.article, body="Changed again"))
    with pytest.raises(ReadingConflict, match="changed again"):
        store.reading_links.update(linked.id, expected_revision=1, expected_version=old_version)
    assert store.reading_links.list("measurement")[0].version == linked.version


def test_remove_only_link_preserves_article_annotations_and_progress(store):
    linked = attach(store)
    article = store.library.get("my-guide")
    store.library.annotate("my-guide", bookmarked=True, note="Private article note")
    progress = store.save("measurement", status="exploring", note="Learning note", expected_revision=0)
    store.reading_links.remove(linked.id, expected_revision=1)
    assert store.library.get("my-guide") == article
    assert store.library.annotation("my-guide")["note"] == "Private article note"
    assert store.progress("measurement") == progress
    assert not store.reading_links.list("measurement")


def test_deleted_article_stays_visible_and_reimport_compares_exact_version(store):
    linked = attach(store)
    original = store.library.get("my-guide")
    with store.library.connect() as db:
        db.execute("DELETE FROM knowledge_articles WHERE slug='my-guide'")
    missing = store.reading_links.list("measurement")[0]
    assert missing.id == linked.id and missing.state == "missing"
    assert missing.saved_title == original.title
    with pytest.raises(ReadingConflict, match="no longer installed"):
        store.reading_links.open_link(linked.id, expected_revision=1)
    store.library.upsert(original)
    assert store.reading_links.list("measurement")[0].state == "current"
    store.library.upsert(replace(original, body="New version under same slug"))
    assert store.reading_links.list("measurement")[0].state == "changed"


def test_stale_link_revision_and_delete_recreate_are_not_silent_overwrites(store):
    first = attach(store)
    store.library.upsert(replace(store.library.get("my-guide"), body="New text"))
    version = store.reading_links.preview("my-guide").version
    second = store.reading_links.update(first.id, expected_revision=1, expected_version=version)
    with pytest.raises(ReadingConflict):
        store.reading_links.remove(first.id, expected_revision=1)
    store.reading_links.remove(second.id, expected_revision=2)
    third = attach(store)
    assert third.id > second.id
    with pytest.raises(ReadingConflict):
        store.reading_links.remove(second.id, expected_revision=2)
    assert store.reading_links.list("measurement") == (third,)


def test_concurrent_identical_links_create_one_record(store):
    version = store.reading_links.preview("my-guide").version
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: store.reading_links.link("measurement", "my-guide", expected_version=version), range(2)))
    assert results[0] == results[1]
    assert len(store.reading_links.list("measurement")) == 1


def test_link_insert_failure_rolls_back_without_mutating_articles(store):
    with store.library.connect() as db:
        db.execute("CREATE TRIGGER reject_link BEFORE INSERT ON pathway_reading_links BEGIN SELECT RAISE(ABORT,'simulated error'); END")
    with pytest.raises(sqlite3.IntegrityError, match="simulated"):
        attach(store)
    assert not store.reading_links.list("measurement") and store.library.count() == 1


def test_link_limits_fail_without_truncation(store, monkeypatch):
    monkeypatch.setattr(module, "MAX_LINKS_PER_GOAL", 1)
    attach(store)
    store.library.upsert(replace(store.library.get("my-guide"), slug="second"))
    with pytest.raises(ValueError, match="limit"):
        attach(store, slug="second")
    assert len(store.reading_links.list("measurement")) == 1


def test_no_body_read_for_map_but_body_integrity_checked_before_open(store):
    linked = attach(store)
    with store.library.connect() as db:
        def authorizer(action, table, column, _database, _trigger):
            if action == sqlite3.SQLITE_READ and table == "knowledge_articles" and column == "body":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.set_authorizer(authorizer)
        assert store.reading_links.snapshot(db)[0] == linked
    with store.library.connect() as db:
        db.execute("UPDATE knowledge_articles SET body='Corrupt bytes' WHERE slug='my-guide'")
    # Map compares stored hashes/metadata, not every article body. Open must not
    # mistake that lightweight version check for an actual body-integrity check.
    assert store.reading_links.list("measurement")[0].state == "current"
    with pytest.raises(ValueError, match="checksum mismatch"):
        store.reading_links.open_link(linked.id, expected_revision=1)
    with pytest.raises(ValueError, match="checksum mismatch"):
        store.reading_links.preview("my-guide")


def test_custom_reading_does_not_skip_prerequisites_or_mark_them_practiced(store):
    attach(store, "inventory")
    result = view(store, "inventory")
    assert result.pending_prerequisites == ("measurement",) and not result.next_to_explore
    store.save("measurement", status="practiced", note="Practice recorded", expected_revision=0)
    assert view(store, "inventory").next_to_explore
    assert view(store, "inventory").progress.status == "not_started"
    store.save("measurement", status="needs_review", note="Recheck", expected_revision=1)
    assert not view(store, "inventory").next_to_explore


def test_missing_link_blocks_suggestion_even_with_another_installed_source(store):
    linked = attach(store)
    store.library.upsert(replace(store.library.get("my-guide"), slug="starter-v1-measurement"))
    store.library.upsert(replace(store.library.get("my-guide"), body="Changed"))
    result = view(store)
    assert result.installed_articles and not result.next_to_explore
    assert result.user_links[0].id == linked.id


def test_filters_and_removed_catalog_goals_preserve_associations(store):
    linked = attach(store, "construction")
    assert "construction" in [row.goal.slug for row in store.views(content="reading_available")]
    assert "construction" not in [row.goal.slug for row in store.views(content="guide_needed")]
    tiny = LearningCatalog((LearningGoal("other", "Other", 1, "Test", "Objective", "Exercise", "Requirements"),))
    PathwayStore(store.library, tiny)
    assert store.reading_links.list("construction") == (linked,)


@pytest.mark.parametrize("case", ["future", "unversioned", "missing", "columns"])
def test_unknown_schema_not_silently_rebuilt_or_reset(store, case):
    attach(store)
    with store.library.connect() as db:
        if case == "future":
            db.execute("UPDATE knowledge_state SET value='9' WHERE key='reading_links_schema'")
        elif case == "unversioned":
            db.execute("DELETE FROM knowledge_state WHERE key='reading_links_schema'")
        elif case == "missing":
            db.execute("DROP TABLE pathway_reading_links")
        else:
            db.execute("ALTER TABLE pathway_reading_links ADD COLUMN future TEXT")
    before = store.library.database_path.read_bytes()
    with pytest.raises(ValueError):
        PathwayStore(store.library)
    assert store.library.database_path.read_bytes() == before


def test_invalid_ids_goals_and_digests_never_write(store):
    with pytest.raises(ValueError):
        store.reading_links.link("missing-goal", "my-guide", expected_version="a"*64)
    with pytest.raises(ValueError):
        store.reading_links.link("measurement", "my-guide", expected_version="bad")
    with pytest.raises(ValueError):
        store.reading_links.preview(None)
    with pytest.raises(ValueError):
        store.reading_links.remove(True, expected_revision=1)
    with pytest.raises(ReadingConflict):
        store.reading_links.preview("missing-article")
    assert not store.reading_links.list("measurement")


def test_no_network_or_personal_annotation_copy(store, monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network attempted")
    for name in ("socket", "getaddrinfo", "create_connection"):
        monkeypatch.setattr(socket, name, blocked)
    store.library.annotate("my-guide", bookmarked=True, note="PRIVATE_SENTINEL")
    linked = attach(store)
    assert store.reading_links.open_link(linked.id, expected_revision=1)
    assert "PRIVATE_SENTINEL" not in str(store.reading_links.list("measurement"))
