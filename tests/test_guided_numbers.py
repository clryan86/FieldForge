"""Number meanings, conserved quantities, prior work and the stepped desktop UI."""

import hashlib
import json
import os
import socket
import xml.etree.ElementTree as ET
from copy import deepcopy
from fractions import Fraction

import pytest

from fieldforge.knowledge.education import Work, check, lessons, worksheet
from fieldforge.knowledge.education_visuals import counter_scene, counters_svg, validate_counters


def course():
    return [lesson for lesson in lessons() if lesson.track == "Guided: Numbers & operations"]


def test_all_590_preexisting_question_identities_are_unchanged():
    original = [(lesson.id, q.id, q.fingerprint) for lesson in lessons()
                if lesson.id.startswith(("guide-", "read-", "write-", "evidence-", "library-")) for q in lesson.questions]
    assert len(original) == 590
    assert hashlib.sha256(json.dumps(original, separators=(",", ":")).encode()).hexdigest() == (
        "2040cbca616861b9f29d09b8722a6622501210afb105364ae566c88197b6302c")
    assert next(lesson for lesson in lessons() if lesson.id == "guide-fractions").prerequisites == ("fraction-quantity",)


def test_arithmetic_keys_and_choice_meanings_match_the_authored_stories():
    expected = [(5 + 3, 0, 6 - 4), (3 * 10 + 6, 4 * 10, 2 * 10 + 13),
                (8 + 5, 26 + 17, 14 - 9), (13 - 5, 43 - 18, 16 - 9),
                (4 * 3, 5 * 4, 0 * 6), (18 // 3, 17 // 5, 17 % 5)]
    meanings = ["still eight", "Fifty ones", "One ten", "Regroup 43", "4 + 4 + 4", "Four:"]
    source_snippets = [("five marks", "three marks"), ("three tens and six", "two tens and thirteen"),
                       ("26 cards", "17", "fourteen"), ("43 cards", "18", "sixteen"),
                       ("Four boxes", "three cards each", "Five rows"), ("Eighteen", "three people", "Seventeen", "five")]
    assert len(course()) == 6
    for lesson, keys, meaning, snippets in zip(course(), expected, meanings, source_snippets):
        assert [q.kind for q in lesson.questions] == ["number"] * 3 + ["choice", "reflection", "reflection"]
        assert [Fraction(q.answer) for q in lesson.questions[:3]] == list(keys)
        assert all(text in lesson.questions[0].passage for text in snippets)
        assert all(q.passage == lesson.questions[0].passage for q in lesson.questions)
        assert meaning in dict(lesson.questions[3].choices)[lesson.questions[3].answer]


def test_every_misconception_is_useful_offline_and_full_groups_are_not_fractional(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Foundations must work offline")
    monkeypatch.setattr(socket, "socket", forbidden)
    for lesson in course():
        for question in lesson.questions:
            if question.kind == "reflection":
                draft = Work(response="An explanation that has not been independently checked")
                assert check(question, draft)[0] == draft
                continue
            result, feedback = check(question, Work(response=question.answer))
            assert result.result == "correct" and question.explanation in feedback
            for wrong, reason in question.mistakes:
                result, feedback = check(question, Work(response=wrong))
                assert result.result == "retry" and reason in feedback
    question = course()[-1].questions[1]
    result, feedback = check(question, Work(response="3.4"))
    assert result.result == "retry" and "full groups of whole cards" in feedback


def test_all_diagram_steps_account_for_every_represented_one():
    # Expected totals are independently computed from each worked example.
    totals = [(7, 7, 7), (24, 24, 24), (27 + 15, 27 + 15, 42),
              (42, 42, 42 - 17), (3 * 4, 12, 12), (14, 3 * 4 + 2, 12 + 2)]
    for lesson, expected in zip(course(), totals):
        assert len(lesson.diagram["steps"]) == 3
        for index, total in enumerate(expected):
            step = lesson.diagram["steps"][index]
            assert sum(10 * g["tens"] + g["ones"] for g in step["groups"]) == total
            for width in (300, 640, 1200):
                scene = counter_scene(lesson.diagram, index, width)
                assert sum(mark.kind in {"ten", "one"} for mark in scene) == total
                for mark in scene:
                    if mark.kind == "text":
                        assert 0 < mark.coords[0] < width and 0 < mark.coords[1] < 174
                    else:
                        left, top, right, bottom = mark.coords
                        assert 0 <= left < right <= width and 0 <= top < bottom <= 174


@pytest.mark.parametrize("field,value", [("tens", -1), ("tens", 6), ("tens", True),
                                         ("ones", 19), ("ones", 2.5), ("label", "")])
def test_bad_counter_groups_are_rejected(field, value):
    diagram = deepcopy(course()[0].diagram)
    diagram["steps"][0]["groups"][0][field] = value
    with pytest.raises(ValueError, match="Invalid counting group"):
        validate_counters(diagram)


def test_exports_contain_every_step_source_and_escaped_personal_work():
    for lesson in course():
        records = tuple(Work(response="<script>private()</script>", reasoning="tens < ones") for _ in lesson.questions)
        page = worksheet(lesson, records)
        assert page.count("<svg") == 3 and page.count("<details>") == 1
        assert "&lt;script&gt;private()" in page and "<script>" not in page
        for index, step in enumerate(lesson.diagram["steps"]):
            assert step["caption"] in page
            diagram = ET.fromstring(counters_svg(lesson.diagram, index))
            ns = {"s": "http://www.w3.org/2000/svg"}
            ones = len(diagram.findall(".//s:circle", ns))
            cells = sum(rect.attrib["fill"] == "#dcebf0" for rect in diagram.findall(".//s:rect", ns))
            assert ones == sum(g["ones"] for g in step["groups"])
            assert cells == 10 * sum(g["tens"] for g in step["groups"])
            assert all("href" not in attr for item in diagram.iter() for attr in item.attrib)
        assert "Practice source text" in page
    diagram = deepcopy(course()[0].diagram)
    assert all(float(dot.attrib["r"]) == 6 for dot in ET.fromstring(counters_svg(diagram, 0)).findall(
        ".//{http://www.w3.org/2000/svg}circle"))
    diagram["steps"][0]["title"] = "<unsafe> & title"
    assert ET.fromstring(counters_svg(diagram, 0)).find("{http://www.w3.org/2000/svg}title").text == "<unsafe> & title"


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


def test_gui_default_course_all_steps_legacy_diagrams_and_preserved_practice(root, tmp_path):
    from fieldforge.ui.education import EducationTab
    tab = EducationTab(root, tmp_path / "study.db")
    tab.pack(fill="both", expand=True)
    assert tab.lesson.id == "number-count" and len(tab.tree.get_children()) == 6
    for lesson in course():
        tab.open_lesson(lesson.id)
        root.update()
        assert tab.diagram_previous.instate(["disabled"])
        for index, step in enumerate(lesson.diagram["steps"]):
            root.update()
            assert tab.diagram_index == index
            assert len(tab.diagram.find_withtag("one")) == sum(g["ones"] for g in step["groups"])
            assert len(tab.diagram.find_withtag("ten")) == 10 * sum(g["tens"] for g in step["groups"])
            for widget in (tab.diagram, tab.diagram_previous, tab.diagram_next, tab.diagram_caption):
                assert widget.winfo_ismapped()
                assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + root.winfo_width()
                assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height()
            tab.diagram_next.invoke()
        assert tab.diagram_next.instate(["disabled"]) and tab.diagram_index == 2
        tab.diagram_previous.invoke()
        assert tab.diagram_index == 1
    tab.open_lesson("number-add")
    tab.pages.select(tab.practice_page)
    tab.move_question(1)
    tab.response.insert("1.0", "33")
    tab.check_button.invoke()
    assert tab.work.result == "retry" and "lost the ten" in tab.feedback.get("1.0", "end")
    tab.hint_button.invoke()
    tab.response.delete("1.0", "end")
    tab.response.insert("1.0", "43")
    tab.check_button.invoke()
    saved = tab.work
    tab.pages.select(tab.read_page)
    tab.diagram_next.invoke()
    tab.diagram_next.invoke()
    assert tab.work == saved  # Viewing a worked diagram never changes an answer.
    tab.pages.select(tab.practice_page)
    root.update()
    for widget in (tab.check_button, tab.reveal_button, tab.review_button, tab.status_label):
        assert widget.winfo_ismapped()
        assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height()
    tab.open_lesson("evidence-measure")
    root.update()
    assert not tab.diagram_controls.winfo_ismapped()
    assert len([item for item in tab.diagram.find_all() if tab.diagram.type(item) == "rectangle"]) == 3
    tab.open_lesson("read-notice")
    root.update()
    assert not tab.diagram_frame.winfo_ismapped()
    tab.open_lesson("guide-fractions")
    tab.open_prerequisite()
    root.update()
    assert tab.lesson.id == "fraction-quantity"
    assert tab.track.get() == "Guided: Fractions & quantities"
    assert tab.tree.selection() == ("fraction-quantity",)
    assert tab.can_close()
    tab.destroy()
    reopened = EducationTab(root, tmp_path / "study.db")
    reopened.open_lesson("number-add")
    reopened.move_question(1)
    assert reopened.work == saved


def test_gui_division_choice_writing_export_and_resume(root, tmp_path, monkeypatch):
    from fieldforge.ui.education import EducationTab
    tab = EducationTab(root, tmp_path / "study.db")
    tab.pack(fill="both", expand=True)
    tab.open_lesson("number-divide")
    tab.pages.select(tab.practice_page)
    tab.move_question(3)
    tab.choices.winfo_children()[1].invoke()
    tab.check_button.invoke()
    assert tab.work.result == "retry" and "two cards" in tab.feedback.get("1.0", "end")
    tab.choices.winfo_children()[0].invoke()
    tab.check_button.invoke()
    assert tab.work.result == "correct"
    tab.next.invoke()
    tab.response.insert("1.0", "Three cards per person in one story; three groups in the other.")
    tab.reveal_button.invoke()
    tab.review_button.invoke()
    assert tab.work.result == "draft" and tab.work.reflection == "needs practice"
    target = tmp_path / "division.html"
    monkeypatch.setattr("fieldforge.ui.education.filedialog.asksaveasfilename", lambda **_kw: str(target))
    tab.export()
    text = target.read_text(encoding="utf-8")
    assert text.count("<svg") == 3 and "[D3]" in text and "Three cards per person" in text
    assert tab.can_close()
    tab.destroy()
    reopened = EducationTab(root, tmp_path / "study.db")
    reopened.resume()
    assert reopened.lesson.id == "number-divide" and reopened.question_index == 4
    assert reopened.work.reflection == "needs practice"
