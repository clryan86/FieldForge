"""Actual app, source search, personal reading links and portable-copy compatibility."""

import pytest

from fieldforge.app import FieldForgeApp
from fieldforge.knowledge import KnowledgeLibrary
from fieldforge.knowledge.assistant import ReferenceAssistant
from fieldforge.knowledge.binder import capture_binder, render_binder
from fieldforge.knowledge.foundations import foundation_articles, install_foundations
from fieldforge.knowledge.pathways import PathwayStore
from fieldforge.knowledge.pocket import capture_pocket, render_pocket
from fieldforge.knowledge.starter import install_starter


def test_app_search_starter_and_pathways_preserve_separation(tmp_path):
    app = FieldForgeApp(tmp_path/'app.db')
    store = PathwayStore(app.knowledge)
    install_starter(app.knowledge)
    progress = store.save('measurement', status='exploring', note='PRIVATE_LEARNING', expected_revision=0)
    install_foundations(app.knowledge, acknowledged=True)
    assert app.knowledge.count() == 32
    article = foundation_articles()[7]
    report = ReferenceAssistant(app.db.path).ask('cubic units')
    assert any(reference.article.slug == article.slug for reference in report.references)
    assert store.progress('measurement') == progress
    assert store.reading_links.list('measurement') == ()
    preview = store.reading_links.preview(article.slug)
    link = store.reading_links.link('measurement', article.slug, expected_version=preview.version)
    assert store.reading_links.open_link(link.id, expected_revision=1) == article
    assert store.progress('measurement') == progress


def test_full_snapshot_recovers_lesson_bodies_and_independent_private_notes(tmp_path):
    from fieldforge.core.recovery import create_verified_backup, restore_verified_copy
    app = FieldForgeApp(tmp_path/'app.db')
    install_foundations(app.knowledge, acknowledged=True)
    article = foundation_articles()[0]
    app.knowledge.annotate(article.slug, bookmarked=True, note='PRIVATE_ARTICLE\n\n')
    preview = create_verified_backup(app.db.path, tmp_path/'all.ffbackup')
    assert dict(preview.counts)['Knowledge articles'] == 20
    target = restore_verified_copy(preview, tmp_path/'restored.db', active_database=app.db.path)
    recovered = KnowledgeLibrary(target)
    assert tuple(recovered.get(a.slug) for a in foundation_articles()) == foundation_articles()
    assert recovered.annotation(article.slug)['note'] == 'PRIVATE_ARTICLE\n\n'


@pytest.mark.parametrize('format', ['binder', 'pocket'])
def test_complete_content_pack_fits_portable_exports_and_keeps_explanations(tmp_path, format):
    library = KnowledgeLibrary(tmp_path/'library.db')
    install_foundations(library, acknowledged=True)
    slugs = tuple(a.slug for a in foundation_articles())
    for slug in slugs:
        library.annotate(slug, bookmarked=True, note='DO_NOT_EXPORT_PRIVATE_NOTE')
    snapshot = capture_pocket(library.database_path, slugs=slugs) if format == 'pocket' else capture_binder(library.database_path, slugs=slugs)
    content = render_pocket(snapshot) if format == 'pocket' else render_binder(snapshot)
    assert len(snapshot.entries) == 20
    assert b'DO_NOT_EXPORT_PRIVATE_NOTE' not in content
    assert content.count(b'WORKED ANSWERS') == 20
    assert b'Correct arithmetic does not establish real-world competence' in content
    assert foundation_articles()[-1].checksum.encode() in content
