"""Recompute revision outcomes while keeping the baseline's acceptance rules fixed."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, localcontext

from fieldforge.blueprints.acceptance import evaluate_rules
from fieldforge.blueprints.engine import digest
from fieldforge.blueprints.geometry import analyze_envelopes
from fieldforge.blueprints.projects import compare_designs
from fieldforge.blueprints.render import normalized_document

SCOPE = (
    "Both snapshots are checked again with this version of FieldForge. Baseline acceptance "
    "rules are evaluated unchanged on both designs, including rules removed or changed later. "
    "Passing more checks is not a certification or an overall design-quality score. "
    "Geometry measures axis-aligned rectangular envelopes, not joints or structural capacity. "
    "Larger clearances and fewer contacts are not inherently better."
)


def _identity(value):
    return {"title": value["design"]["title"], "design_sha256": value["design_sha256"],
            "snapshot_sha256": digest(value), "status": value["status"],
            "validation": value["validation"]}


def _outcome(before, after):
    if before == after:
        return "still_" + after
    if before == "passed":
        return "regressed"
    if after == "passed":
        return "now_passes"
    return "became_unresolved" if after == "unresolved" else "now_resolved_failing"


def _criterion(rule):
    if rule is None:
        return None
    fields = {key: rule[key] for key in ("metric", "target", "operator", "value", "unit")}
    if fields["metric"].startswith("pair."):
        fields["target"] = "/".join(sorted(fields["target"].split("/")))
    return fields


def _acceptance(before, after):
    baseline = before["request"].get("acceptance_rules", [])
    current = after["request"].get("acceptance_rules", [])
    left = before["validation"].get("acceptance", [])
    right = evaluate_rules(after["request"]["mode"], after["design"], baseline,
                           after["validation"]["schedule"])
    fixed = [{"id": a["id"], "rule": rule, "before": a, "after": b,
              "outcome": _outcome(a["status"], b["status"])}
             for rule, a, b in zip(baseline, left, right)]
    a_rules = {rule["id"]: rule for rule in baseline}
    b_rules = {rule["id"]: rule for rule in current}
    changes = []
    for key in sorted(a_rules.keys() | b_rules.keys()):
        a, b = a_rules.get(key), b_rules.get(key)
        if a == b:
            continue
        kind = ("added" if a is None else "removed" if b is None else
                "criteria_changed" if _criterion(a) != _criterion(b) else "description_changed")
        changes.append({"id": key, "change": kind, "before": a, "after": b})
    return {"baseline_count": len(baseline), "outcomes": dict(Counter(r["outcome"] for r in fixed)),
            "fixed_baseline": fixed, "rule_changes": changes,
            "current_results": after["validation"].get("acceptance", [])}


def _spans(parts, analyzed):
    if not analyzed:
        return None
    with localcontext() as context:
        context.prec = 400
        return [str(max(Decimal(str(p["position_mm"][i])) + Decimal(str(p["size_mm"][i]))
                        for p in parts) - min(Decimal(str(p["position_mm"][i])) for p in parts))
                for i in range(3)]


def _parts(before, after):
    # Duplicate IDs make correspondence ambiguous. Do not silently take the last instance.
    if any(len({p["id"] for p in parts}) != len(parts) for parts in (before, after)):
        return {"status": "unresolved", "reason": "Part IDs are duplicated; parts cannot be matched.",
                "changes": []}
    left, right = ({p["id"]: p for p in parts} for parts in (before, after))
    changes = []
    for key in sorted(left.keys() | right.keys()):
        a, b = left.get(key), right.get(key)
        fields = [field for field in ("name", "material", "size_mm", "position_mm", "source_ids")
                  if a is None or b is None or a[field] != b[field]]
        if fields:
            changes.append({"id": key, "change": "added" if a is None else "removed" if b is None else "changed",
                            "fields": fields, "before": a, "after": b})
    return {"status": "compared", "reason": "", "changes": changes}


def _geometry(before, after):
    left, right = (analyze_envelopes(value["design"]["parts"]) for value in (before, after))
    analyzed = [value["summary"]["status"] == "analyzed" for value in (left, right)]
    result = {"status": "compared" if all(analyzed) else "unresolved",
              "before": left["summary"], "after": right["summary"],
              "span_before_mm": _spans(before["design"]["parts"], analyzed[0]),
              "span_after_mm": _spans(after["design"]["parts"], analyzed[1]),
              "parts": _parts(before["design"]["parts"], after["design"]["parts"]),
              "pairs": [], "unchanged_pairs": 0}
    if not all(analyzed):
        # Missing geometry is not evidence that previous overlaps disappeared.
        return result
    a_pairs, b_pairs = ({tuple(p["part_ids"]): p for p in value["pairs"]} for value in (left, right))
    for key in sorted(a_pairs.keys() | b_pairs.keys()):
        a, b = a_pairs.get(key), b_pairs.get(key)
        if a == b:
            result["unchanged_pairs"] += 1
            continue
        direction = "not_comparable"
        if a is not None and b is not None:
            # Rounded display strings may be equal for distinct distances.
            a_squared, b_squared = (Decimal(p["clearance_squared_mm2"]) for p in (a, b))
            direction = "increased" if b_squared > a_squared else "decreased" if b_squared < a_squared else "unchanged"
        result["pairs"].append({"part_ids": list(key),
                                "change": "added" if a is None else "removed" if b is None else "changed",
                                "clearance_change": direction, "before": a, "after": b})
    return result


def compare_results(before, after):
    """Read-only, same-maker comparison. Bound by input schemas; pair changes are complete."""
    before, after = normalized_document(before), normalized_document(after)
    mode = before["request"]["mode"]
    if mode != after["request"]["mode"]:
        raise ValueError("Result comparisons require two blueprints from the same maker.")
    result = {"format": "fieldforge-blueprint-comparison", "version": 1, "mode": mode,
              "scope": SCOPE, "before": _identity(before), "after": _identity(after),
              "acceptance": _acceptance(before, after), "fields": compare_designs(before, after)}
    if mode == "engineering":
        result["geometry"] = _geometry(before, after)
    return result


def comparison_text(result, *, pair_limit=200):
    """Accessible UI/report text; exported JSON retains every changed pair."""
    if type(pair_limit) is not int or not 1 <= pair_limit <= 3540:
        raise ValueError("Pair display limit must be between 1 and 3540.")
    acceptance = result["acceptance"]
    lines = ["Recomputed revision comparison", result["scope"],
             f"Before: {result['before']['title']}\nAfter: {result['after']['title']}",
             "Fixed baseline acceptance limits"]
    if not acceptance["fixed_baseline"]:
        lines.append("No baseline limits were recorded. No acceptance improvement can be established.")
    for row in acceptance["fixed_baseline"]:
        rule = row["rule"]
        lines.append(f"{row['id']} — {rule['label']}: {row['outcome'].replace('_', ' ')}\n"
                     f"Fixed: {rule['metric']} {rule['target']} {rule['operator']} {rule['value']} {rule['unit']}\n"
                     f"Before ({row['before']['status']}): {row['before']['detail']}\n"
                     f"After ({row['after']['status']}): {row['after']['detail']}")
    lines.append("Rule changes (separate from fixed-baseline outcomes)")
    lines.extend(f"{row['id']}: {row['change'].replace('_', ' ')}\n"
                 f"Before: {row['before']}\nAfter: {row['after']}" for row in acceptance["rule_changes"])
    if not acceptance["rule_changes"]:
        lines.append("No rule changes.")
    if "geometry" in result:
        geometry = result["geometry"]
        lines.append(f"Envelope comparison: {geometry['status']}\n"
                     f"Overall XYZ spans (mm): {geometry['span_before_mm']} → {geometry['span_after_mm']}")
        for side in ("before", "after"):
            summary = geometry[side]
            lines.append(f"{side.capitalize()}: {summary['status']}; " + (
                f"{summary['overlap_pairs']} overlapping pairs; {summary['face_contact_pairs']} face contacts; "
                f"{summary['connected_groups']} touching/overlapping groups."
                if summary["status"] == "analyzed" else " ".join(summary["problems"])))
        if geometry["status"] == "unresolved":
            lines.append("Pair changes cannot be determined. Unresolved geometry is not a clean result.")
        parts = geometry["parts"]
        lines.append("Part changes: " + (parts["reason"] or str(len(parts["changes"]))))
        for row in parts["changes"]:
            lines.append(f"{row['id']}: {row['change']} ({', '.join(row['fields'])})\n"
                         f"Before: {row['before']}\nAfter: {row['after']}")
        lines.append(f"Changed pairs: {len(geometry['pairs'])}; unchanged: {geometry['unchanged_pairs']}")
        for row in geometry["pairs"][:pair_limit]:
            def pair_text(pair):
                if pair is None:
                    return "absent"
                approx = "approximately " if pair["clearance_is_rounded"] else ""
                return (f"{pair['relation'].replace('_', ' ')}; clearance {approx}{pair['clearance_mm']} mm; "
                        f"XYZ gaps {pair['gap_mm']} mm; XYZ overlap {pair['overlap_mm']} mm")
            lines.append(f"{' / '.join(row['part_ids'])}: {row['change']}; clearance {row['clearance_change']}\n"
                         f"Before: {pair_text(row['before'])}\nAfter: {pair_text(row['after'])}")
        if len(geometry["pairs"]) > pair_limit:
            lines.append(f"{len(geometry['pairs']) - pair_limit} additional pair changes omitted from this view. "
                         "Export comparison.json for all changed pairs.")
    lines.append("Current acceptance results (current rules)")
    lines.extend(f"{row['id']}: {row['status']} — {row['detail']}" for row in acceptance["current_results"])
    if not acceptance["current_results"]:
        lines.append("No current limits recorded.")
    for side in ("before", "after"):
        lines.append(f"{side.capitalize()} recomputed checks — {result[side]['status']}")
        lines.extend(f"{row['severity']}: {row['issue']}" for row in result[side]["validation"]["issues"])
    lines.append("Recorded field changes")
    lines.extend(f"{row['path']}\nBefore: {row['before']}\nAfter: {row['after']}"
                 for row in result["fields"]["changes"])
    if result["fields"]["truncated"]:
        lines.append("Additional field changes omitted. Inspect both full snapshots.")
    elif not result["fields"]["changes"]:
        lines.append("No design, request, source or critique changes.")
    return "\n\n".join(lines)
