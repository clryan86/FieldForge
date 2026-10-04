"""Full-checkout integration: linked starter content, private exports, and recovery."""

from fieldforge.core.snapshot import export_snapshot, restore_snapshot
from fieldforge.knowledge import KnowledgeLibrary
from fieldforge.knowledge.packs import export_pack, import_pack
from fieldforge.knowledge.pathways import PathwayStore, default_catalog
from fieldforge.knowledge.starter import install_starter, starter_articles


def test_catalog_links_match_real_bundled_articles():
    source_ids = {article.slug for article in starter_articles()}
    mapped = {slug for goal in default_catalog().goals for slug in goal.articles}
    assert mapped <= source_ids
    assert len(mapped) == 12


def test_learning_notes_are_never_silently_included_in_article_packs(tmp_path):
    library = KnowledgeLibrary(tmp_path / "library.db")
    install_starter(library)
    store = PathwayStore(library)
    store.save("water", status="exploring", note="PRIVATE_PATHWAY_MARKER", expected_revision=0)
    library.annotate("starter-v1-water-storage", bookmarked=True, note="ARTICLE_NOTE_MARKER")
    public = export_pack(library, tmp_path / "public.json")
    assert "PRIVATE_PATHWAY_MARKER" not in public.read_text(encoding="utf-8")
    assert "ARTICLE_NOTE_MARKER" not in public.read_text(encoding="utf-8")
    personal = export_pack(library, tmp_path / "article-notes.json", include_personal=True)
    assert "PRIVATE_PATHWAY_MARKER" not in personal.read_text(encoding="utf-8")
    assert "ARTICLE_NOTE_MARKER" in personal.read_text(encoding="utf-8")
    import_pack(library, public)
    assert store.progress("water").note == "PRIVATE_PATHWAY_MARKER"


def test_full_snapshot_restores_pathways_alongside_articles_and_notes(tmp_path):
    library = KnowledgeLibrary(tmp_path / "source.db")
    install_starter(library)
    store = PathwayStore(library)
    saved = store.save("water", status="exploring", note="Exact private note\n\n", expected_revision=0)
    library.annotate("starter-v1-water-storage", bookmarked=True, note="Article note")
    snapshot = export_snapshot(library.database_path, tmp_path / "complete.ffbackup")
    restored = tmp_path / "restored.db"
    restore_snapshot(snapshot, restored)
    target_library = KnowledgeLibrary(restored)
    target = PathwayStore(target_library)
    assert target.progress("water") == saved
    assert target_library.annotation("starter-v1-water-storage")["note"] == "Article note"
    assert target_library.count() == 12
    assert len(target.views()) == 24
    assert any(row.installed_articles for row in target.views())
