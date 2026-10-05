"""Learner workflow, exact feedback, durable work and desktop integration."""

import json
import os
import socket
from dataclasses import replace

import pytest

from fieldforge.app import FieldForgeApp
from fieldforge.core.recovery import create_verified_backup, restore_verified_copy
from fieldforge.knowledge.education import StudyStore, Work, check, lessons, revise, worksheet


def test_every_numeric_key_and_misconception_is_exact_and_offline(monkeypatch):
    def forbidden(*_a, **_kw):
        raise AssertionError("Education must work without a network")
    monkeypatch.setattr(socket, "socket", forbidden)
    guided = [lesson for lesson in lessons() if lesson.track == "Guided: Measure & plan"]
    assert len(guided) == 5 and len(lessons()) == 196
    assert sum(len(lesson.questions) for lesson in lessons()) == 650
    for lesson in guided:
        assert lesson.diagram["description"] and len(lesson.paragraphs) >= 6
        for q in lesson.questions:
            if q.kind == "reflection":
                assert check(q, Work(response="anything"))[0].result == "draft"
                continue
            result, feedback = check(q, Work(response=q.answer))
            assert result.result == "correct" and result.attempts == 1
            assert q.explanation in feedback
            for wrong, reason in q.mistakes:
                result, feedback = check(q, Work(response=wrong))
                assert result.result == "retry" and reason in feedback
    assert check(guided[0].questions[0], Work(response="0.375"))[0].result == "correct"
    assert check(guided[0].questions[0], Work(response="0.38"))[0].result == "retry"


@pytest.mark.parametrize("response", ["", "1/0", "NaN", "0.375 cm", "3 / 8", "3/8+0", "9" * 100000])
def test_invalid_numeric_input_does_not_consume_a_check(response):
    original = Work(response=response)
    value, feedback = check(lessons()[0].questions[0], original)
    assert value == original and feedback


def test_explained_answers_remain_self_review_not_automatic_grades(tmp_path):
    store = StudyStore(tmp_path / "study.db")
    lesson = lessons()[0]
    q = lesson.questions[-1]
    work = store.save(lesson.id, q, Work(response="Half a 10 cm strip is 5 cm; half of 18 is 9.",
                                        revealed=True, reflection="explained it"))
    loaded = StudyStore(store.path).read(lesson.id, q)
    assert loaded == work and loaded.result == "draft" and loaded.attempts == 0
    assert "1 self-reviewed" in store.summary(lesson)
    assert revise(work, "Now changed", "").reflection == ""


def test_editing_rechecking_support_and_conflicts_preserve_work(tmp_path):
    store = StudyStore(tmp_path / "study.db")
    lesson, q = lessons()[1], lessons()[1].questions[0]
    work, _ = check(q, Work(response="11", reasoning="I used the endpoint."))
    saved = store.save(lesson.id, q, work)
    assert saved.result == "retry" and "Review needed" == store.summary(lesson)
    stale = StudyStore(store.path).read(lesson.id, q)
    revised = revise(saved, "8", "Subtract the starting position.")
    assert revised.result == "draft"
    revised, feedback = check(q, replace(revised, hints=1))
    assert "after a hint" in feedback
    newest = store.save(lesson.id, q, revised)
    with pytest.raises(ValueError, match="another window"):
        store.save(lesson.id, q, replace(stale, response="99"))
    assert store.read(lesson.id, q) == newest
    with pytest.raises(ValueError, match="another window"):
        store.save(lesson.id, q, Work(response="4"))
    assert store.read(lesson.id, replace(q, prompt="A changed question")) == Work()
    assert store.read(lesson.id, q).response == "8"


def test_drafts_notes_and_support_survive_real_backup_restore(tmp_path):
    app = FieldForgeApp(tmp_path / "app.db")
    lesson, q = lessons()[3], lessons()[3].questions[2]
    store = StudyStore(app.db.path)
    saved = store.save(lesson.id, q, Work(response="120", reasoning="Only scaled one side.",
                                        hints=2, revealed=True, attempts=1, result="retry",
                                        reflection="needs practice"))
    backup = create_verified_backup(app.db.path, tmp_path / "study.ffbackup")
    assert dict(backup.counts)["Education practice records"] == 1
    recovered = restore_verified_copy(backup, tmp_path / "recovered.db", active_database=app.db.path)
    assert StudyStore(recovered).read(lesson.id, q) == saved
    assert store.read(lesson.id, q) == saved
    assert store.recent() == (lesson.id, 2)


def test_worksheet_escapes_personal_text_and_separates_answer_key():
    lesson = lessons()[0]
    records = tuple(Work(response='<script>alert("test")</script>', reasoning="A < B & C")
                    for _ in lesson.questions)
    document = worksheet(lesson, records)
    assert "<script>" not in document and "&lt;script&gt;" in document
    assert "<details><summary>Worked answers" in document
    assert "A &lt; B &amp; C" in document and "Hints shown: 0" in document
    assert "<img" not in document and "<iframe" not in document


def test_corrupt_or_false_progress_is_not_silently_overwritten(tmp_path):
    import sqlite3
    store = StudyStore(tmp_path / "study.db")
    q = lessons()[0].questions[0]
    with pytest.raises(ValueError, match="matching numeric"):
        store.save("guide-fractions", q, Work(response="1", result="correct"))
    saved = store.save("guide-fractions", q, Work(response="1"))
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE education_work_v1 SET payload=?", (json.dumps({"unrecognized": "value"}),))
    with pytest.raises(ValueError, match="unreadable"):
        store.read("guide-fractions", q)
    assert saved.revision == 1


@pytest.fixture
def root():
    import tkinter as tk
    try:
        window = tk.Tk()
    except tk.TclError:
        if os.environ.get("FIELDFORGE_REQUIRE_GUI") == "1":
            raise
        pytest.skip("A working Tk display is required; graphical CI enforces this")
    errors = []
    window.report_callback_exception = lambda *args: errors.append(args)
    window.geometry("1000x700")
    yield window
    try:
        window.destroy()
    except tk.TclError:
        pass
    assert not errors


def test_gui_wrong_answer_hint_correction_explanation_navigation_and_reopen(root, tmp_path):
    from fieldforge.ui.education import EducationTab
    tab = EducationTab(root, tmp_path / "study.db")
    tab.pack(fill="both", expand=True)
    tab.open_lesson("guide-length")
    tab.pages.select(tab.practice_page)
    tab.response.insert("1.0", "11")
    tab.reasoning.insert("1.0", "The end label is eleven.")
    tab.check_button.invoke()
    assert "end position" in tab.feedback.get("1.0", "end")
    tab.hint_button.invoke()
    tab.response.delete("1.0", "end")
    tab.response.insert("1.0", "8")
    tab.check_button.invoke()
    assert tab.work.result == "correct" and tab.work.hints == 1 and tab.work.attempts == 2
    tab.next.invoke()
    tab.response.insert("1.0", "72")
    tab.previous.invoke()
    assert tab.response.get("1.0", "end-1c") == "8"
    assert tab.work.hints == 1
    tab.move_question(4)
    tab.response.insert("1.0", "The length stays fixed; the unit changes.")
    tab.reveal_button.invoke()
    tab.explained_button.invoke()
    assert tab.work.reflection == "explained it" and tab.work.result == "draft"
    root.update()
    for widget in (tab.check_button, tab.reveal_button, tab.explained_button, tab.status_label):
        assert widget.winfo_ismapped()
        assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height()
        assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + root.winfo_width()
    assert tab.can_close()
    tab.destroy()
    reopened = EducationTab(root, tmp_path / "study.db")
    reopened.open_lesson("guide-length")
    assert reopened.response.get("1.0", "end-1c") == "8"
    reopened.move_question(4)
    assert reopened.work.reflection == "explained it"


def test_gui_reference_search_drafts_hidden_answers_and_prerequisites(root, tmp_path):
    from fieldforge.ui.education import EducationTab
    tab = EducationTab(root, tmp_path / "study.db")
    tab.pack(fill="both", expand=True)
    tab.track.set("All lessons")
    tab.search.set("Fractions as equal parts")
    tab.refresh()
    assert tab.lesson.id == "library-15"
    assert tab.question.explanation not in tab.reading.get("1.0", "end")
    assert tab.question.explanation not in tab.feedback.get("1.0", "end")
    tab.response.insert("1.0", "My partial draft")
    tab.next.invoke()
    tab.previous.invoke()
    assert tab.response.get("1.0", "end-1c") == "My partial draft"
    tab.reveal_button.invoke()
    assert tab.question.explanation in tab.feedback.get("1.0", "end")
    tab.open_lesson("guide-area")
    tab.open_prerequisite()
    assert tab.lesson.id == "guide-length"


def test_gui_save_failure_keeps_draft_and_export_can_rescue_it(root, tmp_path, monkeypatch):
    from fieldforge.ui.education import EducationTab
    tab = EducationTab(root, tmp_path / "study.db")
    tab.pack(fill="both", expand=True)
    tab.response.insert("1.0", "My unsaved work")
    def failure(*_a):
        raise ValueError("simulated write failure")
    monkeypatch.setattr(tab.store, "save", failure)
    assert not tab.open_lesson("guide-area")
    assert tab.lesson.id == "number-count"
    assert tab.response.get("1.0", "end-1c") == "My unsaved work"
    target = tmp_path / "rescue.html"
    monkeypatch.setattr("fieldforge.ui.education.filedialog.asksaveasfilename", lambda **_kw: str(target))
    tab.export()
    assert "My unsaved work" in target.read_text(encoding="utf-8")


def test_packaged_education_workflow(root, tmp_path):
    from fieldforge.package_checks import verify_education_workspace
    verify_education_workspace(root, tmp_path)
