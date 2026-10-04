"""Conservative, model-free contradictions among exact user acceptance limits."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, localcontext

from fieldforge.blueprints.acceptance import validate_rules

SCOPE = (
    "Checks exact pair-distance intervals, axis-gap/3D-distance compatibility, contact relations "
    "and conflicting exact text requirements on the same target. Other numeric metrics retain "
    "their existing evaluator and are not analyzed for contradictions here. No detected conflict "
    "does not prove feasibility. Conflict groups are explanatory, not minimal conflicting subsets."
)


def _interval(rules, metric):
    low, high = Decimal(0), None
    for rule in rules:
        if rule["metric"] != metric:
            continue
        value = Decimal(str(rule["value"]))
        if rule["operator"] in (">=", "="):
            low = max(low, value)
        if rule["operator"] in ("<=", "="):
            high = value if high is None else min(high, value)
    return low, high


def _pair_conflict(rules):
    """Necessary conditions only. Decimal precision also covers squared subnormal gaps."""
    metrics = ["pair.clearance", "pair.gap_x", "pair.gap_y", "pair.gap_z"]
    distance, *gaps = [_interval(rules, metric) for metric in metrics]
    for metric, (low, high) in zip(metrics, [distance, *gaps]):
        if high is not None and low > high:
            return f"{metric} requires at least {low} mm and at most {high} mm."
    relations = {r["value"] for r in rules if r["metric"] == "pair.relation"}
    if len(relations) > 1:
        return "The same pair requires incompatible relations: " + ", ".join(sorted(relations)) + "."
    if relations and relations != {"separated"} and (distance[0] > 0 or any(low > 0 for low, _ in gaps)):
        return "Contact or overlap requires zero clearance and zero axis gaps, but a positive minimum is required."
    if relations == {"separated"} and (distance[1] == 0 or all(high == 0 for _, high in gaps)):
        return "Separation requires positive clearance, but the limits force all distance to zero."
    with localcontext() as context:
        context.prec = 800
        minimum_squared = sum(low * low for low, _ in gaps)
        if distance[1] is not None and minimum_squared > distance[1] * distance[1]:
            return (f"Axis-gap minima require a squared clearance of at least {minimum_squared} mm2, "
                    f"exceeding the clearance maximum squared ({distance[1] * distance[1]} mm2).")
        if all(high is not None for _, high in gaps):
            maximum_squared = sum(high * high for _, high in gaps)
            if distance[0] * distance[0] > maximum_squared:
                return (f"Axis-gap maxima allow a squared clearance of at most {maximum_squared} mm2, "
                        f"below the clearance minimum squared ({distance[0] * distance[0]} mm2).")
    return None


def analyze_constraints(mode, rules):
    validate_rules(mode, rules)
    pairs, texts = defaultdict(list), defaultdict(list)
    examined = []
    for rule in rules:
        if rule["metric"].startswith("pair."):
            pairs["/".join(sorted(rule["target"].split("/")))].append(rule)
        elif rule["unit"] == "text":
            texts[(rule["metric"], rule["target"])].append(rule)
        else:
            continue
        examined.append(rule["id"])
    conflicts = []
    for target, group in sorted(pairs.items()):
        reason = _pair_conflict(group)
        if reason:
            conflicts.append({"target": target, "rule_ids": sorted(r["id"] for r in group), "reason": reason})
    for (metric, target), group in sorted(texts.items()):
        if len({r["value"] for r in group}) > 1:
            conflicts.append({"target": target, "rule_ids": sorted(r["id"] for r in group),
                              "reason": f"{metric} requires different exact text values for the same target."})
    return {"format": "fieldforge-constraint-analysis", "version": 1,
            "status": "conflicts_detected" if conflicts else "no_conflict_detected",
            "scope": SCOPE, "examined_rule_ids": sorted(examined),
            "not_analyzed_rule_ids": sorted(r["id"] for r in rules if r["id"] not in examined),
            "conflicts": conflicts}


def require_consistent_rules(mode, rules):
    result = analyze_constraints(mode, rules)
    if result["conflicts"]:
        ids = sorted({key for row in result["conflicts"] for key in row["rule_ids"]})
        raise ValueError("Conflicting acceptance limits: " + ", ".join(ids) + ". "
                         "Review the limits before generation; no model can satisfy them together. "
                         + result["conflicts"][0]["reason"])
    return result
