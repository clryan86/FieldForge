"""Independent data calculations, legacy work, chart exports and native practice."""

import hashlib
import json
import os
import socket
import xml.etree.ElementTree as ET
from dataclasses import replace
from fractions import Fraction

import pytest

from fieldforge.knowledge.education import (
    StudyStore,
    Work,
    bar_chart,
    chart_svg,
    check,
    lessons,
    worksheet,
)


def course():
    return [lesson for lesson in lessons() if lesson.track == "Guided: Investigate & reason"]


def test_all_566_shipped_questions_keep_their_work_identity():
    original = [(lesson.id, q.id, q.fingerprint) for lesson in lessons()
                if lesson.id.startswith(("guide-", "read-", "write-", "library-")) for q in lesson.questions]
    assert len(original) == 566
    assert hashlib.sha256(json.dumps(original, separators=(",", ":")).encode()).hexdigest() == (
        "8827feb3ec06a417bb6ef88846899413238734e82f68926ced6be97d3536df3d")


def test_keys_and_charts_match_the_authored_data_and_denominators():
    # Compute independently from the values learners are given, not answer keys.
    readings = [Fraction("10.0"), Fraction("10.2"), Fraction("10.1")]
    x, y = [12, 14, 16], [8, 10, 12]
    a, b = [7, 8, 8, 9, 8], [9, 9, 10, 9, 8]
    expected = [(sum(readings) / 3, max(readings) - min(readings)),
                (Fraction(sum(x), 3), Fraction(sum(x) - sum(y), 3)),
                (Fraction(8, 10), (Fraction(8, 10) - Fraction(18, 30)) * 100),
                (sum(b), Fraction(sum(b), 50) * 100)]
    snippets = [("10.0 cm", "10.2 cm", "10.1 cm"),
                ("12, 14, 16 seconds", "8, 10, 12 seconds"),
                ("8 successes out of 10", "18 successes out of 30"),
                ("7, 8, 8, 9, 8", "9, 9, 10, 9, 8")]
    charts = [readings, [sum(x) / 3, sum(y) / 3], [80, 60], [sum(a) * 2, sum(b) * 2]]
    correct_meanings = [("trusted reference", "Preserve 10.9"),
                        ("extra practice changed together", "planned X-first and Y-first"),
                        ("higher success proportion", "assign versions by chance"),
                        ("missing records and the small sample", "without inventing")]
    assert len(course()) == 4
    for lesson, numbers, source, chart, meanings in zip(course(), expected, snippets, charts, correct_meanings):
        assert [q.kind for q in lesson.questions] == ["number", "number", "choice", "choice", "reflection", "reflection"]
        assert all(text in lesson.questions[0].passage for text in source)
        assert all(q.passage == lesson.questions[0].passage for q in lesson.questions)
        assert [Fraction(q.answer) for q in lesson.questions[:2]] == list(numbers)
        assert [Fraction(str(value)) for _, value in lesson.diagram["bars"]] == [Fraction(str(v)) for v in chart]
        for q, meaning in zip(lesson.questions[2:4], meanings):
            assert meaning in dict(q.choices)[q.answer]
        assert lesson.questions[0].passage in lesson.paragraphs[-1]


def test_authored_feedback_is_offline_and_writing_is_not_automatically_graded(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Evidence practice must work offline")
    monkeypatch.setattr(socket, "socket", forbidden)
    for lesson in course():
        for q in lesson.questions:
            if q.kind == "reflection":
                work = Work(response="Unsupported prose is still an unchecked draft.")
                assert check(q, work)[0] == work
                continue
            checked, feedback = check(q, Work(response=q.answer))
            assert checked.result == "correct" and q.explanation in feedback
            for wrong, reason in q.mistakes:
                checked, feedback = check(q, Work(response=wrong))
                assert checked.result == "retry" and reason in feedback
    q = course()[2].questions[0]
    assert check(q, Work(response="0.8"))[0].result == "correct"
    assert check(q, Work(response="8/40"))[0].result == "retry"


def test_changed_source_preserves_original_work_and_versions_new_attempt(tmp_path):
    lesson = course()[0]
    q = lesson.questions[0]
    store = StudyStore(tmp_path / "study.db")
    saved = store.save(lesson.id, q, Work(response="10.1", attempts=1, result="correct"))
    revised = replace(q, passage=q.passage.replace("10.2 cm", "11.2 cm"))
    assert store.read(lesson.id, revised) == Work()
    assert store.read(lesson.id, q) == saved


def test_charts_share_zero_baseline_and_geometry_across_widths():
    for lesson in course():
        diagram = lesson.diagram
        for width in (300, 640, 1200):
            for (_, value), (label, left, top, right, bottom, text) in zip(diagram["bars"], bar_chart(diagram, width)):
                assert left == 102 and 25 < top < bottom < 103
                assert 102 <= right <= width - 70
                assert (right - left) / (width - 172) == pytest.approx(value / diagram["maximum"])
                assert Fraction(text) == Fraction(str(value)) and label


@pytest.mark.parametrize("change", [
    {"maximum": 0}, {"maximum": float("inf")}, {"bars": [["x", -1]]},
    {"bars": [["x", 101]]}, {"bars": [["x", float("nan")]]},
    {"bars": [["x", True]]}, {"bars": []}, {"bars": [["x", 1]] * 4},
])
def test_invalid_charts_cannot_misrepresent_values(change):
    diagram = {**course()[2].diagram, **change}
    with pytest.raises(ValueError, match="Invalid bar chart"):
        bar_chart(diagram)


def test_export_retains_dataset_chart_and_personal_report_with_escaped_text():
    lesson = course()[-1]
    work = tuple(Work(response="<script>private()</script>", reasoning="A < B") for _ in lesson.questions)
    page = worksheet(lesson, work)
    assert page.count("PICTURE INSTRUCTIONS PILOT — FICTIONAL PRACTICE DATA") == 1
    assert "[R2]" in page and "<svg" in page and "<details>" in page
    assert "&lt;script&gt;private()" in page and "<script>" not in page
    document = ET.fromstring(chart_svg({**lesson.diagram, "title": "<unsafe> & text"}))
    ns = {"s": "http://www.w3.org/2000/svg"}
    assert document.find("s:title", ns).text == "<unsafe> & text"
    assert len(document.findall(".//s:rect", ns)) == 2
    assert document.find("s:desc", ns).text == lesson.diagram["description"]
    assert all("href" not in key for element in document.iter() for key in element.attrib)


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


def test_gui_data_chart_numeric_choice_report_and_reopen(root, tmp_path, monkeypatch):
    from fieldforge.ui.education import EducationTab
    tab = EducationTab(root, tmp_path / "study.db")
    tab.pack(fill="both", expand=True)
    tab.track.set("Guided: Investigate & reason")
    tab.refresh()
    assert tab.lesson.id == "evidence-measure" and len(tab.tree.get_children()) == 4
    for lesson in course():
        assert tab.open_lesson(lesson.id)
        root.update()
        bars = [item for item in tab.diagram.find_all() if tab.diagram.type(item) == "rectangle"]
        assert len(bars) == len(lesson.diagram["bars"])
        for item in bars:
            left, top, right, bottom = tab.diagram.coords(item)
            assert 0 <= left <= right < tab.diagram.winfo_width()
            assert 0 <= top < bottom < tab.diagram.winfo_height()
    tab.open_lesson("evidence-sample")
    tab.pages.select(tab.practice_page)
    tab.question_pages.select(tab.source_text.frame)
    assert "[S3]" in tab.source_text.get("1.0", "end")
    tab.response.insert("1.0", "8/40")
    tab.check_button.invoke()
    assert "Forty combines" in tab.feedback.get("1.0", "end") and tab.work.result == "retry"
    tab.hint_button.invoke()
    tab.response.delete("1.0", "end")
    tab.response.insert("1.0", "4/5")
    tab.reasoning.insert("1.0", "Use the ten attempts in the large-print group.")
    tab.check_button.invoke()
    assert tab.work.result == "correct" and tab.work.hints == 1
    tab.move_question(2)
    tab.choices.winfo_children()[0].invoke()
    tab.check_button.invoke()
    assert tab.work.result == "retry"
    tab.choices.winfo_children()[1].invoke()
    tab.check_button.invoke()
    assert tab.work.result == "correct"
    tab.open_lesson("evidence-report")
    tab.pages.select(tab.practice_page)
    root.update()
    tab.move_question(4)
    tab.response.insert("1.0", "B had 90% among returned placements; four sheets are missing.")
    assert str(tab.check_button["state"]) == "disabled"
    tab.reveal_button.invoke()
    tab.review_button.invoke()
    assert tab.work.result == "draft" and tab.work.reflection == "needs practice"
    target = tmp_path / "report.html"
    monkeypatch.setattr("fieldforge.ui.education.filedialog.asksaveasfilename", lambda **_kw: str(target))
    tab.export()
    assert "four sheets are missing" in target.read_text(encoding="utf-8")
    assert "<svg" in target.read_text(encoding="utf-8")
    root.update()
    for widget in (tab.reveal_button, tab.review_button, tab.status_label):
        assert widget.winfo_ismapped()
        assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height()
    assert tab.can_close()
    tab.destroy()
    reopened = EducationTab(root, tmp_path / "study.db")
    reopened.resume()
    assert reopened.lesson.id == "evidence-report" and reopened.question_index == 4
    assert reopened.work.reflection == "needs practice"
    reopened.open_lesson("evidence-sample")
    assert reopened.response.get("1.0", "end-1c") == "4/5"
    assert reopened.work.hints == 1
