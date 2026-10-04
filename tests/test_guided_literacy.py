"""Text-evidence checks, legacy progress compatibility and literacy GUI workflows."""

import hashlib
import json
import os
import socket
from dataclasses import replace

import pytest

from fieldforge.knowledge.education import StudyStore, Work, check, lessons, revise, worksheet


def literacy():
    return [lesson for lesson in lessons() if lesson.track == "Guided: Read & write"]


def test_all_preexisting_questions_keep_their_shipped_fingerprints():
    original = [(lesson.id, q.id, q.fingerprint) for lesson in lessons()
                if lesson.track != "Guided: Read & write" for q in lesson.questions]
    assert len(original) == 541
    digest = hashlib.sha256(json.dumps(original, separators=(",", ":")).encode()).hexdigest()
    assert digest == "24c8ea7602882bc80fd054483ce05f87e5ff3ecc36e859e6cee2a21f3ca8ba1c"


def test_every_choice_and_distractor_has_grounded_feedback_without_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Reading and writing practice must work offline")
    monkeypatch.setattr(socket, "socket", forbidden)
    course = literacy()
    assert len(course) == 5 and sum(len(lesson.questions) for lesson in course) == 25
    for lesson in course:
        assert len(lesson.paragraphs) >= 7
        assert sum(q.kind == "reflection" for q in lesson.questions) == 2
        for q in lesson.questions:
            assert q.passage and q.passage in lesson.paragraphs[-1]
            if q.kind == "reflection":
                original = Work(response="A plausible but unchecked explanation")
                assert check(q, original)[0] == original
                continue
            correct, feedback = check(q, Work(response=" " + q.answer.lower() + " "))
            assert correct.result == "correct" and correct.response == q.answer
            assert q.explanation in feedback and "written" not in correct.result
            for wrong, reason in q.mistakes:
                result, feedback = check(q, Work(response=wrong))
                assert result.result == "retry" and result.attempts == 1
                assert reason in feedback
                assert q.explanation not in feedback  # Targeted prompt, not the full key.


def test_authored_choice_keys_point_to_the_claims_in_the_sources():
    # Independent semantic expectations: assertions connect selected text to
    # the stated evidence rather than simply feeding each key back to itself.
    expected = [
        ("Room 2", "large-print", "borrow a book"),
        ("gust", "missing number", "account for all the cards"),
        ("important limits", "neither trial-label", "prior experience"),
        ("cards 1–4 in the envelope", "extra 3 aside", "when to check"),
        ("Six additional", "how many you can provide", "unsupported urgency"),
    ]
    for lesson, meanings in zip(literacy(), expected):
        for q, meaning in zip(lesson.questions[:3], meanings):
            assert meaning in dict(q.choices)[q.answer]


@pytest.mark.parametrize("response", ["", "D", "AB", "Room 2", "<script>", "B" * 10000])
def test_invalid_choices_do_not_consume_attempts(response):
    q = literacy()[0].questions[0]
    original = Work(response=response)
    result, feedback = check(q, original)
    assert result == original and "Choose one" in feedback


def test_new_question_context_versions_work_but_old_math_progress_still_loads(tmp_path):
    store = StudyStore(tmp_path / "work.db")
    maths = lessons()[0]
    old = store.save(maths.id, maths.questions[0], Work(response="3/8", attempts=1, result="correct"))
    lesson, q = literacy()[0], literacy()[0].questions[0]
    attempt, _ = check(q, Work(response="A", reasoning="I used the earlier poster."))
    saved = store.save(lesson.id, q, replace(attempt, hints=1))
    assert store.read(lesson.id, q) == saved
    changed = replace(q, passage=q.passage + "\nA revised notice.")
    assert changed.fingerprint != q.fingerprint
    assert store.read(lesson.id, changed) == Work()
    assert store.read(lesson.id, replace(q, choices=(("A", "A different choice"), *q.choices[1:]))) == Work()
    assert StudyStore(store.path).read(maths.id, maths.questions[0]) == old
    with pytest.raises(ValueError, match="matching numeric or choice"):
        store.save(lesson.id, q, replace(saved, result="correct"))
    corrected, _ = check(q, revise(saved, "B", "N5 replaces the poster."))
    new = store.save(lesson.id, q, corrected)
    assert new.result == "correct" and new.hints == 1 and new.attempts == 2
    assert revise(new, "A", new.reasoning).result == "draft"


def test_export_contains_source_once_choices_writing_and_no_active_content():
    lesson = literacy()[0]
    work = tuple(Work(response="<img src=x onerror=alert(1)>", reasoning="A < B") for _ in lesson.questions)
    page = worksheet(lesson, work)
    assert page.count("<h3 id='passage-") == 1  # One shared source in the practice section.
    assert page.count("READING TABLE — FICTIONAL PRACTICE NOTICE") == 1
    assert "A. The library hall" in page and "B. Room 2" in page and "[N5]" in page
    assert "&lt;img src=x" in page and "<img src=x" not in page
    assert "Answer checks: 0" in page and "<details>" in page


@pytest.fixture
def root():
    import tkinter as tk
    try:
        window = tk.Tk()
    except tk.TclError:
        if os.environ.get("FIELDFORGE_REQUIRE_GUI") == "1":
            raise
        pytest.skip("Graphical CI requires a functioning display")
    errors = []
    window.report_callback_exception = lambda *args: errors.append(args)
    window.geometry("1000x700")
    yield window
    window.destroy()
    assert not errors


def test_gui_select_read_explain_correct_export_and_reopen(root, tmp_path, monkeypatch):
    from fieldforge.ui.education import EducationTab
    tab = EducationTab(root, tmp_path / "study.db")
    tab.pack(fill="both", expand=True)
    assert "Guided: Read & write" in tab.track_picker["values"]
    tab.track.set("Guided: Read & write")
    tab.refresh()
    assert tab.lesson.id == "read-notice" and len(tab.tree.get_children()) == 5
    tab.pages.select(tab.practice_page)
    tab.question_pages.select(tab.source_text.frame)
    assert "[N5]" in tab.source_text.get("1.0", "end")
    assert tab.question.explanation not in tab.feedback.get("1.0", "end")
    choices = tab.choices.winfo_children()
    choices[0].invoke()
    tab.check_button.invoke()
    assert tab.work.result == "retry" and "older poster" in tab.feedback.get("1.0", "end")
    tab.hint_button.invoke()
    choices[1].invoke()
    tab.reasoning.insert("1.0", "N5 tells us the old poster is replaced.")
    tab.check_button.invoke()
    assert tab.work.result == "correct" and tab.work.hints == 1
    tab.next.invoke()
    tab.previous.invoke()
    assert tab.choice_response.get() == "B"
    assert tab.reasoning.get("1.0", "end-1c").startswith("N5")
    tab.move_question(3)
    assert str(tab.check_button["state"]) == "disabled"
    tab.response.insert("1.0", "Use Room 2 on Saturday from 2 to 3 p.m.")
    tab.reveal_button.invoke()
    tab.review_button.invoke()
    assert tab.work.reflection == "needs practice" and tab.work.result == "draft"
    target = tmp_path / "reading.html"
    monkeypatch.setattr("fieldforge.ui.education.filedialog.asksaveasfilename", lambda **_kw: str(target))
    tab.export()
    assert "[N5]" in target.read_text(encoding="utf-8")
    assert "Use Room 2 on Saturday" in target.read_text(encoding="utf-8")
    root.update()
    for widget in (tab.reveal_button, tab.review_button, tab.status_label):
        assert widget.winfo_ismapped()
        assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height()
        assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + root.winfo_width()
    assert tab.can_close()
    tab.destroy()
    reopened = EducationTab(root, tmp_path / "study.db")
    reopened.resume()
    assert reopened.lesson.id == "read-notice" and reopened.question_index == 3
    assert reopened.work.reflection == "needs practice"
    reopened.move_question(-3)
    assert reopened.choice_response.get() == "B"


def test_gui_choice_drafts_save_on_navigation_and_corrupt_start_has_no_callback_error(root, tmp_path):
    from fieldforge.ui.education import EducationTab
    tab = EducationTab(root, tmp_path / "study.db")
    tab.open_lesson("read-notice")
    tab.choices.winfo_children()[2].invoke()
    tab.next.invoke()
    tab.previous.invoke()
    assert tab.choice_response.get() == "C" and tab.work.result == "draft"
    tab.open_lesson("guide-length")
    assert tab.question_pages.tab(tab.source_text.frame, "state") == "hidden"
    tab.response.insert("1.0", "8")
    tab.check_button.invoke()
    assert tab.work.result == "correct"
    tab.destroy()
    import sqlite3
    with sqlite3.connect(tmp_path / "corrupt.db") as db:
        db.execute("CREATE TABLE education_work_v1(lesson,question,fingerprint,payload,revision,PRIMARY KEY(lesson,question,fingerprint))")
        db.execute("INSERT INTO education_work_v1 VALUES(?,?,?,?,?)",
                   ("guide-fractions", "q1", lessons()[0].questions[0].fingerprint, '{"bad":"value"}', 1))
    broken = EducationTab(root, tmp_path / "corrupt.db")
    assert broken.lesson is None and "Could not open" in broken.status.get()
    broken.check_answer()
    broken.hint()
    broken.reveal()
    broken.reflect("explained it")
    assert broken.open_lesson("read-notice")
