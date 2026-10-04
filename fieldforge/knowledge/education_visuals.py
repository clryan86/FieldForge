"""Shared geometry for stepwise counting models in Tk and offline worksheets."""

from __future__ import annotations

import html
from dataclasses import dataclass


@dataclass(frozen=True)
class CounterMark:
    kind: str
    coords: tuple[float, ...]
    text: str = ""


def validate_counters(diagram: dict) -> None:
    steps = diagram.get("steps", [])
    if not isinstance(steps, list) or not 1 <= len(steps) <= 6 or not diagram.get("description"):
        raise ValueError("Counting diagram needs steps and a description")
    for step in steps:
        if (not isinstance(step, dict) or not isinstance(step.get("title"), str)
                or not 1 <= len(step["title"]) <= 36 or not isinstance(step.get("caption"), str)
                or not 1 <= len(step["caption"]) <= 160):
            raise ValueError("Counting step needs a short title and caption")
        groups = step.get("groups", [])
        if not isinstance(groups, list) or not 1 <= len(groups) <= 4:
            raise ValueError("Counting step needs one to four groups")
        for group in groups:
            if (not isinstance(group, dict) or not isinstance(group.get("label"), str)
                    or not 1 <= len(group["label"]) <= 12
                    or type(group.get("tens")) is not int or not 0 <= group["tens"] <= 5
                    or type(group.get("ones")) is not int or not 0 <= group["ones"] <= 18):
                raise ValueError("Invalid counting group")


def counter_scene(diagram: dict, index: int, width: float = 640) -> tuple[CounterMark, ...]:
    validate_counters(diagram)
    if type(index) is not int or not 0 <= index < len(diagram["steps"]) or not 300 <= width <= 10000:
        raise ValueError("Invalid counting step or width")
    groups = diagram["steps"][index]["groups"]
    panel = (width - 24 - 6 * (len(groups) - 1)) / len(groups)
    result = [CounterMark("text", (width / 2, 10), "Rod = ten ones; circle = one")]
    for i, group in enumerate(groups):
        left = 12 + i * (panel + 6)
        center = left + panel / 2
        result.append(CounterMark("box", (left, 20, left + panel, 165)))
        result.append(CounterMark("text", (center, 31), group["label"]))
        tens, ones = group["tens"], group["ones"]
        start = center - (tens * 9 - 2) / 2
        for rod in range(tens):
            x = start + rod * 9
            for cell in range(10):
                y = 46 + cell * 5
                result.append(CounterMark("ten", (x, y, x + 7, y + 5)))
        columns = min(ones, 5)
        start = center - max(0, columns - 1) * 10 / 2
        for one in range(ones):
            x, y = start + one % 5 * 10, 113 + one // 5 * 11
            result.append(CounterMark("one", (x - 3, y - 3, x + 3, y + 3)))
        if not tens and not ones:
            result.append(CounterMark("text", (center, 89), "Empty: 0"))
    return tuple(result)


def counters_svg(diagram: dict, index: int) -> str:
    marks = counter_scene(diagram, index)
    step = diagram["steps"][index]
    escape = html.escape
    description = "; ".join(f"{g['label']}: {g['tens']} tens and {g['ones']} ones" for g in step["groups"])
    parts = ["<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 640 174' width='640' height='174' "
             "style='max-width:100%;height:auto' role='img'>",
             f"<title>{escape(step['title'])}</title><desc>{escape(description)}</desc>",
             "<g font-family='sans-serif' font-size='11' fill='#18394a'>"]
    for mark in marks:
        if mark.kind == "text":
            x, y = mark.coords
            parts.append(f"<text x='{x}' y='{y}' text-anchor='middle' dominant-baseline='middle'>{escape(mark.text)}</text>")
        else:
            x, y, right, bottom = mark.coords
            if mark.kind == "one":
                parts.append(f"<circle cx='{(x + right) / 2}' cy='{(y + bottom) / 2}' r='3' fill='#2c7f99'/>")
            else:
                fill = "#dcebf0" if mark.kind == "ten" else "none"
                parts.append(f"<rect x='{x}' y='{y}' width='{right - x}' height='{bottom - y}' "
                             f"fill='{fill}' stroke='#18394a' stroke-width='0.7'/>")
    return "".join(parts) + "</g></svg>"
