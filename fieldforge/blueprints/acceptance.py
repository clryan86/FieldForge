"""User-owned, bounded acceptance rules evaluated without model judgment or code."""

from __future__ import annotations

import math
import re

# metric: (maker or all, unit, target description, label, value type)
METRICS = {
    "requirement.exists": ("all", "count", "Requirement ID", "Requirement retained", "number"),
    "step.exists": ("all", "count", "Step ID", "Step retained", "number"),
    "envelope.x": ("engineering", "mm", "", "Overall X span", "number"),
    "envelope.y": ("engineering", "mm", "", "Overall Y span", "number"),
    "envelope.z": ("engineering", "mm", "", "Overall Z span", "number"),
    "part.size_x": ("engineering", "mm", "Part ID", "Part X size", "number"),
    "part.size_y": ("engineering", "mm", "Part ID", "Part Y size", "number"),
    "part.size_z": ("engineering", "mm", "Part ID", "Part Z size", "number"),
    "part.material": ("engineering", "text", "Part ID", "Part material", "string"),
    "part.count": ("engineering", "count", "", "Number of parts", "number"),
    "project.duration": ("project", "day", "", "Dependency schedule duration", "number"),
    "phase.duration": ("project", "day", "Phase ID", "Phase duration", "number"),
    "phase.finish": ("project", "day", "Phase ID", "Phase finish day", "number"),
    "component.count": ("software", "count", "", "Number of components", "number"),
    "component.exists": ("software", "count", "Component ID", "Component retained", "number"),
    "component.kind": ("software", "text", "Component ID", "Component kind", "string"),
    "component.trust_zone": ("software", "text", "Component ID", "Component trust zone", "string"),
}
RULE_FIELDS = {"id", "label", "metric", "target", "operator", "value", "unit"}
IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,39}")


def validate_rules(mode, rules):
    if not isinstance(rules, list) or len(rules) > 30:
        raise ValueError("Acceptance limits must be a list of at most 30 rules.")
    ids = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != RULE_FIELDS:
            raise ValueError("Acceptance rule has missing or unexpected fields.")
        for key in ("id", "label", "metric", "target", "operator", "unit"):
            if not isinstance(rule[key], str) or len(rule[key]) > 160 or any(ord(c) < 32 for c in rule[key]):
                raise ValueError("Invalid acceptance rule text.")
        if not IDENTIFIER.fullmatch(rule["id"]) or rule["id"] in ids or not rule["label"].strip():
            raise ValueError("Acceptance rules need unique IDs and a label.")
        ids.add(rule["id"])
        spec = METRICS.get(rule["metric"])
        if spec is None or spec[0] not in (mode, "all"):
            raise ValueError("Acceptance metric is not supported by this maker.")
        _, unit, target, _, kind = spec
        if rule["unit"] != unit:
            raise ValueError(f"{rule['id']}: acceptance metric requires {unit} units.")
        if (target and not IDENTIFIER.fullmatch(rule["target"])) or (not target and rule["target"]):
            raise ValueError(f"{rule['id']}: invalid acceptance target ID.")
        value = rule["value"]
        if kind == "number":
            if (type(value) not in (int, float) or not 0 <= value <= 1_000_000_000
                    or not math.isfinite(value) or rule["operator"] not in ("<=", "=", ">=")):
                raise ValueError(f"{rule['id']}: use a finite nonnegative numeric limit and <=, = or >=.")
            if rule["metric"].endswith(".exists") and (value != 1 or rule["operator"] != "="):
                raise ValueError("Retention rules must equal 1.")
        elif (not isinstance(value, str) or not value.strip() or len(value) > 160
              or any(ord(c) < 32 for c in value) or rule["operator"] != "="):
            raise ValueError(f"{rule['id']}: text limits require exact equality and 1 to 160 characters.")


def _unique(items, target):
    found = [row for row in items if row["id"] == target]
    if len(found) != 1:
        raise ValueError(f"Target {target} is missing or has duplicate IDs.")
    return found[0]


def _measure(design, metric, target, phase_schedule):
    if metric in ("requirement.exists", "step.exists", "component.exists"):
        collection = {"requirement.exists": "requirements", "step.exists": "steps",
                      "component.exists": "components"}[metric]
        _unique(design[collection], target)
        return 1
    if metric.endswith(".count"):
        items = design["parts" if metric == "part.count" else "components"]
        if len({row["id"] for row in items}) != len(items):
            raise ValueError("Cannot count items with duplicate IDs.")
        return len(items)
    if metric.startswith("envelope."):
        parts = design["parts"]
        if not parts or any(any(size <= 0 for size in row["size_mm"]) for row in parts):
            raise ValueError("Overall span needs positive, dimensioned parts.")
        axis = "xyz".index(metric[-1])
        return (max(p["position_mm"][axis] + p["size_mm"][axis] for p in parts)
                - min(p["position_mm"][axis] for p in parts))
    if metric.startswith("part."):
        part = _unique(design["parts"], target)
        if metric == "part.material":
            return part["material"]
        if any(size <= 0 for size in part["size_mm"]):
            raise ValueError("Part dimensions must be positive.")
        return part["size_mm"]["xyz".index(metric[-1])]
    if metric == "phase.duration":
        return _unique(design["phases"], target)["duration_days"]
    if metric in ("project.duration", "phase.finish"):
        if not phase_schedule:
            raise ValueError("A valid dependency schedule is required.")
        return (max(row["end"] for row in phase_schedule) if metric == "project.duration"
                else _unique(phase_schedule, target)["end"])
    component = _unique(design["components"], target)
    return component[metric.split(".")[1]]


def evaluate_rules(mode, design, rules, phase_schedule):
    """Return pass/fail/unresolved results; callers turn non-passes into blockers."""
    validate_rules(mode, rules)
    results = []
    for rule in rules:
        row = {**rule, "actual": None, "status": "unresolved", "detail": ""}
        try:
            actual = _measure(design, rule["metric"], rule["target"], phase_schedule)
            row["actual"] = actual
            expected = rule["value"]
            if isinstance(expected, str):
                passed = actual == expected
            else:
                # Absorb floating arithmetic noise only, not engineering tolerances.
                equal = math.isclose(actual, expected, rel_tol=0, abs_tol=1e-7)
                passed = equal or (rule["operator"] == "<=" and actual < expected) or (
                    rule["operator"] == ">=" and actual > expected)
            row["status"] = "passed" if passed else "failed"
            row["detail"] = f"{actual} {rule['unit']}; expected {rule['operator']} {expected} {rule['unit']}."
        except ValueError as exc:
            row["detail"] = str(exc)
        results.append(row)
    return results
