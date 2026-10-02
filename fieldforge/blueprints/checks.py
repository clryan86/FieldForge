"""Deterministic design checks. These do not certify engineering or factual safety."""

from __future__ import annotations

import math

from fieldforge.blueprints.schema import blueprint_schema, validate

FORMULAS = {
    "rectangle_area_m2": ({"length": "m", "width": "m"}, "m2",
                          lambda v: v["length"] * v["width"]),
    "box_volume_liters": ({"length": "m", "width": "m", "height": "m"}, "L",
                          lambda v: v["length"] * v["width"] * v["height"] * 1000),
    "dc_power_watts": ({"voltage": "V", "current": "A"}, "W",
                       lambda v: v["voltage"] * v["current"]),
    "battery_runtime_hours": ({"capacity": "Wh", "load": "W", "usable_fraction": "1",
                               "efficiency": "1"}, "h",
                              lambda v: v["capacity"] * v["usable_fraction"]
                              * v["efficiency"] / v["load"]),
    "project_effort_hours": ({"people": "person", "days": "day", "hours_per_day": "h/day"},
                             "person h", lambda v: v["people"] * v["days"] * v["hours_per_day"]),
}


def schedule(items):
    """Topological schedule with deterministic tie order; reject dangling/cyclic edges."""
    by_id = {row["id"]: row for row in items}
    if len(by_id) != len(items):
        raise ValueError("Duplicate IDs in dependency graph.")
    ends, rows = {}, []
    remaining = dict(by_id)
    while remaining:
        ready = [row for row in remaining.values() if all(d in ends for d in row["depends_on"])]
        if not ready:
            raise ValueError("Dependency graph contains a cycle or an unknown prerequisite.")
        for row in ready:
            start = max((ends[d] for d in row["depends_on"]), default=0)
            end = start + row.get("duration_days", 1)
            ends[row["id"]] = end
            rows.append({"id": row["id"], "start": start, "end": end})
            del remaining[row["id"]]
    return rows


def check_design(mode, design, source_ids):
    validate(design, blueprint_schema(mode))
    issues, calculations = [], []

    def issue(message, severity="blocking"):
        issues.append({"severity": severity, "issue": message})

    def walk(value, path="$"):
        if isinstance(value, dict):
            if "source_ids" in value:
                refs = value["source_ids"]
                if len(refs) != len(set(refs)):
                    issue(path + ": duplicate source references.")
                if set(refs) - source_ids:
                    issue(path + ": source references were not in the retrieved evidence.")
                if not refs:
                    issue(path + ": no supporting source; this remains an assumption.", "warning")
            for key, child in value.items():
                walk(child, path + "." + key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(design)
    requirements = {row["id"] for row in design["requirements"]}
    if len(requirements) != len(design["requirements"]):
        issue("Requirement IDs are not unique.")
    covered = {row["requirement_id"] for row in design["checks"]}
    if covered - requirements:
        issue("Acceptance checks reference unknown requirements.")
    if requirements - covered:
        issue("Requirements without acceptance checks: " + ", ".join(sorted(requirements - covered)))
    try:
        schedule(design["steps"])
    except ValueError as exc:
        issue(str(exc))
    if design["questions"]:
        issue("Open questions must be resolved before relying on this design.")
    phase_schedule = []
    if mode == "engineering":
        parts = design["parts"]
        if not parts:
            issue("No dimensioned parts were supplied; drawings cannot be produced.")
        if len({p["id"] for p in parts}) != len(parts):
            issue("Part IDs must be unique.")
        part_ids = {p["id"] for p in parts}
        material_parts = set()
        for material in design["materials"]:
            if set(material["part_ids"]) - part_ids:
                issue("Materials reference an unknown part.")
            if len(material["part_ids"]) != len(set(material["part_ids"])):
                issue("Material part references must be unique within each row.")
            material_parts.update(material["part_ids"])
        if part_ids - material_parts:
            issue("Parts missing from materials: " + ", ".join(sorted(part_ids - material_parts)))
        for part in parts:
            if any(size <= 0 for size in part["size_mm"]):
                issue(f"{part['id']}: all part dimensions must be positive.")
        ids = [row["id"] for row in design["calculations"]]
        if len(ids) != len(set(ids)):
            issue("Calculation IDs must be unique.")
        for row in design["calculations"]:
            expected, unit, function = FORMULAS[row["formula"]]
            inputs = {item["name"]: item for item in row["inputs"]}
            if len(inputs) != len(row["inputs"]) or set(inputs) != set(expected):
                issue(row["id"] + ": calculation inputs do not match the selected formula.")
                continue
            if any(inputs[key]["unit"] != unit for key, unit in expected.items()):
                issue(row["id"] + ": calculation units are inconsistent.")
                continue
            values = {key: item["value"] for key, item in inputs.items()}
            if row["formula"] == "project_effort_hours" and values["hours_per_day"] > 24:
                issue(row["id"] + ": working hours per day cannot exceed 24.")
                continue
            if any(not 0 < value <= 1 for key, value in values.items()
                   if key in {"usable_fraction", "efficiency"}):
                issue(row["id"] + ": fractions must be greater than zero and at most one.")
                continue
            try:
                result = function(values)
                if not math.isfinite(result):
                    raise ValueError()
                calculations.append({"id": row["id"], "formula": row["formula"],
                                     "value": result, "unit": unit})
            except (ArithmeticError, ValueError):
                issue(row["id"] + ": invalid or overflowing calculation.")
        issue("Geometry and arithmetic checks do not establish structural capacity, "
              "potability, electrical protection, code compliance or medical suitability.", "warning")
    elif mode == "project":
        try:
            phase_schedule = schedule(design["phases"])
        except ValueError as exc:
            issue(str(exc))
        issue("Schedule assumes dependencies only; staffing, procurement and calendars "
              "are not resource-leveled.", "warning")
    else:
        components = {c["id"]: c for c in design["components"]}
        if len(components) != len(design["components"]):
            issue("Component IDs must be unique.")
        for connection in design["connections"]:
            if connection["source"] not in components or connection["target"] not in components:
                issue("Connection references an unknown component.")
        issue("Architecture checks validate graph structure, not implementation security.", "warning")
    return {"issues": issues, "calculations": calculations, "schedule": phase_schedule,
            "status": "needs_revision" if any(i["severity"] == "blocking" for i in issues) else "draft"}
