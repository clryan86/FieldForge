"""Small immutable lesson model and bounded exact-number exercise checking.

Exercises are examples, not qualifications. No eval, Python expressions, unit
inference, network, user-record reads, or persistent grades are involved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

_NUMBER = re.compile(r"[+-]?(?:[0-9]{1,16}(?:\.[0-9]{1,16})?|\.[0-9]{1,16}|[0-9]{1,16}/[0-9]{1,16})\Z")


def parse_number(value: str) -> Fraction:
    if not isinstance(value, str) or len(value) > 40 or not _NUMBER.fullmatch(value.strip()):
        raise ValueError("Enter a number such as 12, 0.5 or 1/2, without units, commas or expressions.")
    try:
        return Fraction(value.strip())
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError("A fraction must have a nonzero denominator.") from exc


@dataclass(frozen=True)
class Exercise:
    question: str
    answer: str
    unit: str
    explanation: str

    def __post_init__(self) -> None:
        for name in ("question", "answer", "unit", "explanation"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 2000 or "\x00" in value:
                raise ValueError(f"invalid exercise {name}")
        parse_number(self.answer)

    def check(self, response: str) -> bool:
        """Exact rational comparison; an approximate decimal is not a rounded fraction."""
        return parse_number(response) == parse_number(self.answer)


@dataclass(frozen=True)
class Lesson:
    slug: str
    title: str
    category: str
    prerequisites: tuple[str, ...]
    objective: str
    text: str
    exercises: tuple[Exercise, ...]
    goals: tuple[str, ...] = ()
    reference_title: str = ""
    reference_url: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.slug):
            raise ValueError("invalid lesson ID")
        for name in ("title", "category", "objective", "text"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 100000 or "\x00" in value:
                raise ValueError(f"invalid lesson {name}")
        if not isinstance(self.exercises, tuple) or not self.exercises or any(
            not isinstance(exercise, Exercise) for exercise in self.exercises
        ):
            raise ValueError("lessons need exercises")
        for values in (self.prerequisites, self.goals):
            if not isinstance(values, tuple) or len(values) != len(set(values)) or any(
                not isinstance(value, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value)
                for value in values
            ):
                raise ValueError("invalid lesson prerequisites or suggested goals")
        if bool(self.reference_title) != bool(self.reference_url):
            raise ValueError("related reference needs both a title and URL")
