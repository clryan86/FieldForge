"""Exact fraction comparisons and shared strip/number-line drawings."""

from __future__ import annotations

import html
import math
from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class FractionMark:
    kind: str
    coords: tuple[float, ...]
    text: str = ""


def validate_fraction_steps(diagram: dict) -> None:
    steps = diagram.get("steps", [])
    if not isinstance(steps, list) or not 1 <= len(steps) <= 6 or not diagram.get("description"):
        raise ValueError("Fraction diagram needs steps and a description")
    for step in steps:
        if (not isinstance(step, dict) or not isinstance(step.get("title"), str)
                or not 1 <= len(step["title"]) <= 36 or not isinstance(step.get("caption"), str)
                or not 1 <= len(step["caption"]) <= 180):
            raise ValueError("Fraction step needs a title and caption")
        rows = step.get("rows", [])
        if not isinstance(rows, list) or not 1 <= len(rows) <= 3:
            raise ValueError("Fraction step needs one to three rows")
        for row in rows:
            if (not isinstance(row, dict) or not isinstance(row.get("label"), str)
                    or not 1 <= len(row["label"]) <= 18
                    or type(row.get("parts")) is not int or not 1 <= row["parts"] <= 24
                    or type(row.get("selected")) is not int or not 0 <= row["selected"] <= row["parts"]):
                raise ValueError("Invalid fraction row")


def fraction_scene(diagram: dict, index: int, width: float = 640) -> tuple[FractionMark, ...]:
    validate_fraction_steps(diagram)
    if (type(index) is not int or not 0 <= index < len(diagram["steps"])
            or not math.isfinite(width) or not 300 <= width <= 10000):
        raise ValueError("Invalid fraction step or width")
    left, right = 28, width - 28
    result = []
    for i, row in enumerate(diagram["steps"][index]["rows"]):
        top = 26 + i * 66
        n, d = row["selected"], row["parts"]
        result.append(FractionMark("text", (width / 2, top - 12), f"{row['label']} · {n}/{d} of one whole"))
        for part in range(d):
            x, end = left + (right - left) * part / d, left + (right - left) * (part + 1) / d
            result.append(FractionMark("filled" if part < n else "empty", (x, top, end, top + 17)))
        y = top + 29
        result.append(FractionMark("line", (left, y, right, y)))
        for tick in range(d + 1):
            x = left + (right - left) * tick / d
            result.append(FractionMark("line", (x, y - 3, x, y + 3)))
        endpoint = left + (right - left) * n / d
        result.append(FractionMark("point", (endpoint - 4, y - 4, endpoint + 4, y + 4)))
        result.extend((FractionMark("text", (left, y + 13), "0"),
                       FractionMark("text", (right, y + 13), "1")))
    return tuple(result)


def fraction_svg(diagram: dict, index: int) -> str:
    step = diagram["steps"][index]
    result = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 208" role="img" '
              'style="max-width:640px;width:100%;height:auto">',
              f"<title>{html.escape(step['title'])}</title>",
              f"<desc>{html.escape(step['caption'])} All rows use the same unit whole. "
              + html.escape("; ".join(f"{r['label']}: {r['selected']}/{r['parts']}" for r in step["rows"]))
              + "</desc>"]
    for mark in fraction_scene(diagram, index):
        c = mark.coords
        if mark.kind == "text":
            result.append(f'<text x="{c[0]:g}" y="{c[1]:g}" text-anchor="middle" dominant-baseline="middle" '
                          f'font-family="sans-serif" font-size="12" fill="#18394a">{html.escape(mark.text)}</text>')
        elif mark.kind == "line":
            result.append(f'<line x1="{c[0]:g}" y1="{c[1]:g}" x2="{c[2]:g}" y2="{c[3]:g}" stroke="#18394a"/>')
        elif mark.kind == "point":
            result.append(f'<circle cx="{(c[0]+c[2])/2:g}" cy="{(c[1]+c[3])/2:g}" r="4" fill="#18394a"/>')
        else:
            fill = "#2c7f99" if mark.kind == "filled" else "white"
            result.append(f'<rect x="{c[0]:g}" y="{c[1]:g}" width="{c[2]-c[0]:g}" height="17" '
                          f'fill="{fill}" stroke="#18394a"/>')
    return "".join(result) + "</svg>"


def compare_fractions(a: int, b: int, c: int, d: int) -> str:
    """Describe two amounts on the same unit whole; never use rounded decimals."""
    if (any(type(v) is not int for v in (a, b, c, d)) or not 1 <= b <= 12 or not 1 <= d <= 12
            or not 0 <= a <= b or not 0 <= c <= d):
        raise ValueError("Use 1–12 equal parts and select between zero and all parts.")
    left, right = Fraction(a, b), Fraction(c, d)
    denominator = math.lcm(b, d)
    na, nb = a * (denominator // b), c * (denominator // d)
    relation = "the same amount as" if left == right else "less than" if left < right else "greater than"
    return (f"A: {a}/{b} is {relation} B: {c}/{d}. Both strips represent the same whole.\n\n"
            f"Using equal pieces of size 1/{denominator}: A = {na}/{denominator}; B = {nb}/{denominator}. "
            "Compare the number of these equal pieces, or the positions on the 0–1 number lines.")
