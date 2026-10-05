"""Fraction meanings, exact comparisons, representations and real saved-work UI."""

import hashlib
import json
import os
import socket
import xml.etree.ElementTree as ET
from copy import deepcopy
from fractions import Fraction

import pytest

from fieldforge.knowledge.education import Work, check, lessons, worksheet
from fieldforge.knowledge.fraction_models import (
    compare_fractions,
    fraction_scene,
    fraction_svg,
    validate_fraction_steps,
)


def course():
    return [lesson for lesson in lessons() if lesson.id.startswith("fraction-")]


def test_all_626_preexisting_question_identities_are_unchanged():
    original = [(lesson.id, q.id, q.fingerprint) for lesson in lessons()
                if lesson.id.startswith(("guide-", "read-", "write-", "evidence-", "number-", "library-"))
                for q in lesson.questions]
    assert len(original) == 626
    assert hashlib.sha256(json.dumps(original, separators=(",", ":")).encode()).hexdigest() == (
        "e03d681c7776350ae1744373fe03aa9226f01783fe7bba33c1f6568a2ec0a9fb")


def test_answer_keys_follow_the_practice_cards_and_not_the_worked_examples():
    expected = [(Fraction(5, 6), Fraction(3, 8), 1), (3 * 3, Fraction(5, 6), Fraction(6, 8)),
                (Fraction(1, 3) + Fraction(1, 6), Fraction(5, 8) - Fraction(1, 4), Fraction(2, 5) + Fraction(1, 10)),
                (28 // 4 * 3, 18 // 3 * 2, 7 * 5)]
    meanings = ["4 cm and 6 cm", "fewer equal parts", "equal sixths", "one eighth is 3 cards"]
    snippets = [("six equal-length parts", "five are shaded", "eight equal intervals"),
                ("3 of 4", "three equal smaller", "5/6 and 7/12", "6/8"),
                ("1/3 and 1/6", "1/4 to 5/8", "2/5 and 1/10"),
                ("28 cards", "18 cm", "7 cards")]
    assert len(course()) == 4
    for lesson, keys, meaning, texts in zip(course(), expected, meanings, snippets):
        assert [q.kind for q in lesson.questions] == ["number"] * 3 + ["choice", "reflection", "reflection"]
        assert [Fraction(q.answer) for q in lesson.questions[:3]] == list(keys)
        assert all(t in lesson.questions[0].passage for t in texts)
        assert all(q.passage == lesson.questions[0].passage for q in lesson.questions)
        q = lesson.questions[3]
        assert meaning in dict(q.choices)[q.answer]


def test_all_numeric_and_choice_feedback_works_offline_without_grading_writing(monkeypatch):
    monkeypatch.setattr(socket, "socket", lambda *_a, **_kw: pytest.fail("Fraction learning must work offline"))
    for lesson in course():
        for q in lesson.questions:
            if q.kind == "reflection":
                work = Work(response="This reasoning has not been independently evaluated.")
                assert check(q, work)[0] == work
                continue
            assert check(q, Work(response=q.answer))[0].result == "correct"
            for wrong, explanation in q.mistakes:
                result, feedback = check(q, Work(response=wrong))
                assert result.result == "retry" and explanation in feedback
    q = course()[2].questions[0]
    assert check(q, Work(response="0.5"))[0].result == "correct"
    assert check(q, Work(response="2/4"))[0].result == "correct"
    assert check(q, Work(response="0.499"))[0].result == "retry"


def test_every_lab_comparison_agrees_with_integer_cross_products():
    for b in range(1, 13):
        for a in range(b + 1):
            for d in range(1, 13):
                for c in range(d + 1):
                    relation = "the same amount as" if a * d == c * b else "less than" if a * d < c * b else "greater than"
                    text = compare_fractions(a, b, c, d)
                    assert f"A: {a}/{b} is {relation} B: {c}/{d}" in text
    assert "A = 8/12; B = 9/12" in compare_fractions(2, 3, 3, 4)
    assert "A = 0/12; B = 12/12" in compare_fractions(0, 3, 12, 12)


@pytest.mark.parametrize("values", [(1, 0, 1, 2), (2, 1, 1, 2), (-1, 2, 1, 2), (True, 2, 1, 2),
                                   (1, 13, 1, 2), (1.5, 2, 1, 2)])
def test_lab_rejects_values_outside_its_stated_scope(values):
    with pytest.raises(ValueError):
        compare_fractions(*values)


def test_every_diagram_represents_the_independently_derived_worked_amounts():
    expected = [
        [[(1, 4)], [(3, 4)], [(4, 4), (0, 4)]],
        [[(2, 3), (4, 6)], [(2, 3), (3, 4)], [(8, 12), (9, 12)]],
        [[(1, 4), (1, 2)], [(1, 4), (2, 4), (3, 4)], [(3, 4), (2, 4), (1, 4)]],
        [[(5, 5)], [(1, 5)], [(3, 5), (2, 5)]],
    ]
    for lesson, stages in zip(course(), expected):
        assert len(lesson.diagram["steps"]) == 3
        for index, values in enumerate(stages):
            assert [(r["selected"], r["parts"]) for r in lesson.diagram["steps"][index]["rows"]] == values
            for width in (300, 640, 1200):
                scene = fraction_scene(lesson.diagram, index, width)
                assert sum(mark.kind == "filled" for mark in scene) == sum(n for n, _d in values)
                assert sum(mark.kind in {"filled", "empty"} for mark in scene) == sum(d for _n, d in values)
                points = [m for m in scene if m.kind == "point"]
                for point, (n, d) in zip(points, values):
                    center = (point.coords[0] + point.coords[2]) / 2
                    assert (center - 28) / (width - 56) == pytest.approx(n / d)
                for mark in scene:
                    assert all(0 <= v <= (width if i % 2 == 0 else 208) for i, v in enumerate(mark.coords))


@pytest.mark.parametrize("field,value", [("parts", 0), ("parts", 25), ("parts", True),
                                         ("selected", -1), ("selected", 5), ("label", "")])
def test_invalid_partitions_cannot_produce_a_teaching_diagram(field, value):
    diagram = deepcopy(course()[0].diagram)
    diagram["steps"][0]["rows"][0][field] = value
    with pytest.raises(ValueError, match="Invalid fraction row"):
        validate_fraction_steps(diagram)


def test_every_diagram_exports_as_accessible_svg_and_personal_text_is_escaped():
    ns = {"s": "http://www.w3.org/2000/svg"}
    for lesson in course():
        text = worksheet(lesson, tuple(Work(response="<script>private()</script>") for _q in lesson.questions))
        assert text.count("<svg") == 3 and text.count("<details>") == 1
        assert "<script>" not in text and "&lt;script&gt;private()" in text
        for i, step in enumerate(lesson.diagram["steps"]):
            svg = ET.fromstring(fraction_svg(lesson.diagram, i))
            assert svg.find("s:title", ns).text == step["title"]
            assert "same unit whole" in svg.find("s:desc", ns).text
            assert len(svg.findall("s:circle", ns)) == len(step["rows"])
            assert sum(r.attrib["fill"] == "#2c7f99" for r in svg.findall("s:rect", ns)) == sum(r["selected"] for r in step["rows"])
            assert all("href" not in k for item in svg.iter() for k in item.attrib)


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


def test_gui_lab_keyboard_changes_boundaries_resize_and_does_not_alter_saved_practice(root, tmp_path):
    from fieldforge.ui.education import EducationTab
    tab = EducationTab(root, tmp_path / "study.db")
    tab.pack(fill="both", expand=True)
    tab.open_lesson("fraction-combine")
    tab.pages.select(tab.practice_page)
    tab.response.insert("1.0", "2/9")
    tab.check_button.invoke()
    assert tab.work.result == "retry" and "Adding denominators" in tab.feedback.get("1.0", "end")
    tab.hint_button.invoke()
    tab.response.delete("1.0", "end")
    tab.response.insert("1.0", "3/6")
    tab.reasoning.insert("1.0", "Two sixths plus one sixth makes three sixths.")
    tab.check_button.invoke()
    saved = tab.work
    tab.pages.select(tab.fraction_lab)
    root.update()
    lab = tab.fraction_lab
    assert "the same amount as" in lab.comparison.get("1.0", "end")
    # Use the actual combobox event path, as keyboard selection does.
    lab.values[3].set("6")
    lab.inputs[3].event_generate("<<ComboboxSelected>>")
    lab.values[2].set("3")
    lab.inputs[2].event_generate("<<ComboboxSelected>>")
    root.update()
    assert "A = 3/6; B = 3/6" in lab.comparison.get("1.0", "end")
    assert len(lab.canvas.find_withtag("fraction_point")) == 2
    lab.values[3].set("1")
    lab.inputs[3].event_generate("<<ComboboxSelected>>")
    assert lab.values[2].get() == "1" and "changed from 3 to 1" in lab.comparison.get("1.0", "end")
    lab.values[2].set("0")
    lab.inputs[2].event_generate("<<ComboboxSelected>>")
    assert "greater than B: 0/1" in lab.comparison.get("1.0", "end")
    lab.reset_button.invoke()
    assert "the same amount as" in lab.comparison.get("1.0", "end")
    root.update()
    for widget in (*lab.inputs, lab.reset_button, lab.canvas, lab.comparison, lab.notice):
        assert widget.winfo_ismapped()
        assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + root.winfo_width()
        assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height()
    assert tab.work == saved
    tab.open_lesson("number-count")
    assert tab.pages.tab(lab, "state") == "hidden"
    tab.open_lesson("guide-fractions")
    assert tab.pages.tab(lab, "state") == "normal"
    tab.open_prerequisite()
    root.update()
    assert tab.lesson.id == "fraction-quantity"
    assert tab.tree.selection() == ("fraction-quantity",)
    assert tab.can_close()
    tab.destroy()
    reopened = EducationTab(root, tmp_path / "study.db")
    reopened.open_lesson("fraction-combine")
    assert reopened.work == saved


def test_gui_all_steps_written_review_export_and_resume(root, tmp_path, monkeypatch):
    from fieldforge.ui.education import EducationTab
    tab = EducationTab(root, tmp_path / "study.db")
    tab.pack(fill="both", expand=True)
    for lesson in course():
        tab.open_lesson(lesson.id)
        for index, step in enumerate(lesson.diagram["steps"]):
            root.update()
            assert tab.diagram_index == index
            assert len(tab.diagram.find_withtag("filled")) == sum(r["selected"] for r in step["rows"])
            assert len(tab.diagram.find_withtag("fraction_point")) == len(step["rows"])
            for widget in (tab.diagram, tab.diagram_next, tab.diagram_caption):
                assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height()
            tab.diagram_next.invoke()
        assert tab.diagram_next.instate(["disabled"])
    tab.pages.select(tab.practice_page)
    tab.move_question(5)
    tab.response.insert("1.0", "For 54 cards, one sixth is 9; five sixths is 45; 45 + 9 = 54.")
    tab.reveal_button.invoke()
    tab.review_button.invoke()
    assert tab.work.result == "draft" and tab.work.reflection == "needs practice"
    target = tmp_path / "fractions.html"
    monkeypatch.setattr("fieldforge.ui.education.filedialog.asksaveasfilename", lambda **_kw: str(target))
    tab.export()
    text = target.read_text(encoding="utf-8")
    assert text.count("<svg") == 3 and "[Q4]" in text and "45 + 9 = 54" in text
    assert tab.can_close()
    tab.destroy()
    reopened = EducationTab(root, tmp_path / "study.db")
    reopened.resume()
    assert reopened.lesson.id == "fraction-quantity" and reopened.question_index == 5
    assert reopened.work.reflection == "needs practice"
