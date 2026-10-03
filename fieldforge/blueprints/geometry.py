"""Bounded pairwise analysis of recorded rectangular envelopes, not physical joints."""

from __future__ import annotations

from decimal import Decimal, localcontext
from itertools import combinations

from fieldforge.blueprints.clearance import clearance_measurement
from fieldforge.blueprints.schema import blueprint_schema, validate

RELATIONS = ("overlap", "face_contact", "edge_contact", "point_contact", "separated")
SCOPE = ("Axis-aligned rectangular envelopes only. Overlap may reflect enclosing volumes; "
         "contact does not establish a joint, support, strength or stability. Groups include "
         "all touching or overlapping envelopes. No fabrication tolerance is assumed.")


def _text(value):
    if not value:
        return "0"
    value = value.normalize()
    return format(value, "f") if -6 <= value.adjusted() <= 12 else str(value)


def analyze_envelopes(parts):
    """Classify at most 1,770 pairs with exact arithmetic on recorded decimal values.

    Decimal(str(number)) interprets the JSON-decoded numeric value, not an inferred
    tolerance. 400 digits cover addition/subtraction from 5e-324 through 2e6, the
    finite float range allowed by the part schema. No global context is changed.
    Degenerate/ambiguous geometry returns unresolved, never a partial clean result.
    """
    validate(parts, blueprint_schema("engineering")["properties"]["parts"])
    problems = []
    if not parts:
        problems.append("No parts are recorded.")
    if len({p["id"] for p in parts}) != len(parts):
        problems.append("Part IDs must be unique for pair analysis.")
    if any(any(v <= 0 for v in p["size_mm"]) for p in parts):
        problems.append("Every part needs positive dimensions on all three axes.")
    summary = {"status": "unresolved" if problems else "analyzed", "scope": SCOPE,
               "part_count": len(parts), "pair_count": 0,
               **{relation + "_pairs": 0 for relation in RELATIONS},
               "connected_groups": None, "groups": [], "problems": problems}
    result = {"summary": summary, "pairs": []}
    if problems:
        return result
    # ID order makes reports and tie order independent of part-list reordering.
    parts = sorted(parts, key=lambda part: part["id"])
    adjacency = {p["id"]: set() for p in parts}
    with localcontext() as context:
        context.prec = 400
        boxes = {}
        for part in parts:
            low = [Decimal(str(v)) for v in part["position_mm"]]
            high = [low[a] + Decimal(str(part["size_mm"][a])) for a in range(3)]
            boxes[part["id"]] = low, high
        for a, b in combinations(boxes, 2):
            low_a, high_a = boxes[a]
            low_b, high_b = boxes[b]
            overlap = [min(high_a[i], high_b[i]) - max(low_a[i], low_b[i]) for i in range(3)]
            if any(v < 0 for v in overlap):
                relation = "separated"
            else:
                relation = ("overlap", "face_contact", "edge_contact", "point_contact")[overlap.count(0)]
                adjacency[a].add(b)
                adjacency[b].add(a)
            gaps = [_text(max(-v, 0)) for v in overlap]
            result["pairs"].append({"part_ids": [a, b], "relation": relation,
                                    "overlap_mm": [_text(max(v, 0)) for v in overlap],
                                    "gap_mm": gaps, **clearance_measurement(gaps)})
            summary[relation + "_pairs"] += 1
    remaining = set(adjacency)
    while remaining:
        pending, group = [min(remaining)], set()
        while pending:
            node = pending.pop()
            if node in group:
                continue
            group.add(node)
            pending.extend(adjacency[node] - group)
        summary["groups"].append(sorted(group))
        remaining -= group
    summary["connected_groups"] = len(summary["groups"])
    summary["pair_count"] = len(result["pairs"])
    return result
