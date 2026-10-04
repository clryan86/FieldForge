"""Full-checkout checks with the real app, starter articles, and private progress."""

import json

import pytest

from fieldforge.app import FieldForgeApp
from fieldforge.core.models import HouseholdMember
from fieldforge.knowledge.assistant import ReferenceAssistant
from fieldforge.knowledge.pathways import PathwayStore
from fieldforge.knowledge.starter import install_starter


@pytest.mark.parametrize("question,slug", [
    ("How do I store water?", "starter-v1-water-storage"),
    ("How do I calculate a power budget?", "starter-v1-power-budget"),
    ("How do I track tool maintenance?", "starter-v1-maintenance"),
    ("How can I measure a tabletop?", "starter-v1-measurement"),
])
def test_starter_questions_find_real_article_passages(tmp_path, question, slug):
    app = FieldForgeApp(tmp_path / "app.db")
    install_starter(app.knowledge)
    report = ReferenceAssistant(app.db.path).ask(question)
    first = report.references[0]
    assert first.article.slug == slug
    source = app.knowledge.get(slug)
    assert first.excerpt == source.body[first.start:first.end]
    assert first.excerpt and first.article.reviewed_on == ""
    assert app.knowledge.count() == 12


def test_household_article_notes_and_pathway_notes_are_out_of_scope(tmp_path):
    app = FieldForgeApp(tmp_path / "app.db")
    install_starter(app.knowledge)
    app.add_member(HouseholdMember("Zyxhousehold27391"))
    app.knowledge.annotate("starter-v1-water-storage", bookmarked=True, note="Zyxarticlenote27391")
    PathwayStore(app.knowledge).save("water", status="exploring", note="Zyxlearning27391", expected_revision=0)
    assistant = ReferenceAssistant(app.db.path)
    for secret in ("Zyxhousehold27391", "Zyxarticlenote27391", "Zyxlearning27391"):
        assert not assistant.ask(secret).references
    report = json.dumps(assistant.ask("water").as_dict())
    assert "Zyx" not in report


def test_questions_do_not_change_existing_database_state(tmp_path):
    app = FieldForgeApp(tmp_path / "app.db")
    install_starter(app.knowledge)
    before = app.db.path.read_bytes()
    report = ReferenceAssistant(app.db.path).ask("unlisted pacemaker servicing")
    assert report.status == "no_matches"
    assert app.db.path.read_bytes() == before
