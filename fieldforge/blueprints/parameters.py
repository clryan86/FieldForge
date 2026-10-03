"""Explicit single-part measurement edits, with exact unit conversion and preview."""

from __future__ import annotations

import copy
import re
from decimal import Decimal, DecimalException, localcontext

from fieldforge.blueprints.comparison import compare_results
from fieldforge.blueprints.engine import digest
from fieldforge.blueprints.render import normalized_document

FACTORS = {"mm": Decimal(1), "cm": Decimal(10), "m": Decimal(1000),
           "in": Decimal("25.4"), "ft": Decimal("304.8")}
LENGTH = re.compile(r"([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)\s*(mm|cm|m|in|ft)?", re.IGNORECASE)
NOTICE = ("Only this part's recorded dimensions and position change. Material schedules, "
          "calculation inputs, connections and build steps are not rewritten; review them afterward. "
          "All acceptance limits stay fixed. Applying invalidates the prior model critique. "
          "These are rectangular envelope edits, not fabrication or structural verification.")


def parse_length(text, *, positive=False):
    """Accept decimal/scientific lengths; do not silently round a converted JSON number."""
    if not isinstance(text, str) or len(text) > 80 or not (match := LENGTH.fullmatch(text.strip())):
        raise ValueError("Enter a decimal length with optional mm, cm, m, in or ft (for example 12 in).")
    try:
        amount = Decimal(match[1])
        if amount < 0 or amount > 1_000_000:
            raise ValueError("Measurements must be between 0 and 1,000,000 mm after conversion.")
        if amount and amount.adjusted() < -327:
            # The largest unit factor is 1000; smaller inputs cannot survive as JSON floats.
            # Reject before Decimal multiplication can underflow to zero for extreme exponents.
            raise ValueError("Length is below the supported numeric range; no rounding was applied.")
        with localcontext() as context:
            context.prec = 100
            millimeters = amount * FACTORS[(match[2] or "mm").lower()]
        if millimeters > 1_000_000 or (positive and millimeters == 0):
            raise ValueError("Sizes must be positive; positions may be zero. The maximum is 1,000,000 mm.")
        number = float(millimeters)
        if Decimal(str(number)) != millimeters or (millimeters != 0 and number == 0):
            raise ValueError("This length needs more precision than the blueprint number format supports. "
                             "Use an explicitly rounded measurement; no rounding was applied.")
        return int(number) if number.is_integer() else number
    except DecimalException as exc:
        raise ValueError("Length is outside the supported numeric range.") from exc


def editable_parts(value):
    value = normalized_document(value)
    if value["request"]["mode"] != "engineering":
        raise ValueError("Part measurement editing requires an engineering blueprint.")
    parts = value["design"]["parts"]
    if not parts or len({part["id"] for part in parts}) != len(parts):
        raise ValueError("Part editing requires at least one part and unique part IDs. Repair the structured design first.")
    return copy.deepcopy(parts)


def prepare_part_edit(value, part_id, *, size=None, position=None):
    """Return an isolated candidate and full recomputed comparison; never edit the source."""
    before = normalized_document(copy.deepcopy(value))
    parts = editable_parts(before)
    if not isinstance(part_id, str) or part_id not in {part["id"] for part in parts}:
        raise ValueError("Unknown part ID.")
    if size is None and position is None:
        raise ValueError("Supply at least one size or position change.")
    candidate = copy.deepcopy(before)
    part = next(part for part in candidate["design"]["parts"] if part["id"] == part_id)
    for field, values, positive in (("size_mm", size, True), ("position_mm", position, False)):
        if values is None:
            continue
        if not isinstance(values, (list, tuple)) or len(values) != 3:
            raise ValueError("Provide exactly three lengths for X, Y and Z.")
        converted = []
        for axis, text in zip("XYZ", values):
            try:
                converted.append(parse_length(text, positive=positive))
            except ValueError as exc:
                raise ValueError(f"{field} {axis}: {exc}") from exc
        part[field] = converted
    if candidate["design"] == before["design"]:
        raise ValueError("Part measurements are unchanged.")
    candidate.update(design_sha256=digest(candidate["design"]), review=None,
                     review_error="Part measurements changed; a new review is required.")
    candidate = normalized_document(candidate)
    return {"part_id": part_id, "base_snapshot_sha256": digest(before), "notice": NOTICE,
            "blueprint": candidate, "comparison": compare_results(before, candidate)}
