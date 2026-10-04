from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary


def test_offline_knowledge_search_and_provenance(tmp_path):
    library = KnowledgeLibrary(tmp_path / "fieldforge.db")
    library.upsert(
        KnowledgeArticle(
            slug="water-storage-basics",
            title="Emergency Water Storage",
            body="Store potable water in clean food-grade containers. Rotate stored water.",
            category="water",
            tags=("water", "storage"),
            source_title="Emergency water guidance",
            source_publisher="Example public authority",
            reviewed_on="2026-09-29",
            safety_level="caution",
        )
    )

    results = library.search("potable water")

    assert library.count() == 1
    assert len(results) == 1
    assert results[0].slug == "water-storage-basics"
    assert results[0].source_publisher == "Example public authority"
    assert results[0].safety_level == "caution"


def test_upsert_reindexes_changed_article(tmp_path):
    library = KnowledgeLibrary(tmp_path / "fieldforge.db")
    original = KnowledgeArticle(
        slug="power",
        title="Backup Power",
        body="Battery storage basics.",
        category="energy",
    )
    library.upsert(original)
    library.upsert(
        KnowledgeArticle(
            slug="power",
            title="Backup Power",
            body="Solar charging basics.",
            category="energy",
        )
    )

    assert library.search("battery") == []
    assert library.search("solar")[0].slug == "power"


def test_blank_search_is_safe(tmp_path):
    library = KnowledgeLibrary(tmp_path / "fieldforge.db")
    assert library.search("   ") == []
