"""Create an offline layout from user-entered parts, without a model or fake evidence."""

from __future__ import annotations

from datetime import datetime, timezone

from fieldforge.blueprints.engine import BlueprintRequest, digest
from fieldforge.blueprints.parameters import parse_length
from fieldforge.blueprints.render import normalized_document


def layout_part(name, material, size, position):
    for label, value in (("Part name", name), ("Material", material)):
        if not isinstance(value, str) or not value.strip() or len(value) > 160 or "\x00" in value:
            raise ValueError(f"{label} needs 1 to 160 characters.")
    dimensions = {}
    for key, values, positive in (("size_mm", size, True), ("position_mm", position, False)):
        if not isinstance(values, (list, tuple)) or len(values) != 3:
            raise ValueError("Enter X, Y and Z for both size and position.")
        dimensions[key] = [parse_length(value, positive=positive) for value in values]
    return {"name": name.strip(), "material": material.strip(), **dimensions, "source_ids": []}


def create_layout(title, parts):
    if not isinstance(title, str) or not title.strip() or len(title) > 160 or "\x00" in title:
        raise ValueError("Give the layout a title of 1 to 160 characters.")
    if not isinstance(parts, list) or not 1 <= len(parts) <= 60:
        raise ValueError("Add between 1 and 60 parts before creating a layout.")
    placed = []
    for index, row in enumerate(parts, 1):
        if not isinstance(row, dict) or set(row) != {"name", "material", "size", "position"}:
            raise ValueError("Each part needs a name, material, size and position.")
        placed.append({"id": f"P{index}", **layout_part(**row)})
    request = BlueprintRequest("engineering", "Create a dimensioned layout: " + title.strip(),
        constraints="Use the part dimensions and positions entered by the user. Units are millimetres.",
        resources="Materials are user-entered labels; properties and connections have not been verified.")
    design = {
        "title": title.strip(),
        "summary": "An editable dimensioned layout made from your entered parts. No AI model was used.",
        "assumptions": [{"text": "Each part is represented by an axis-aligned rectangular envelope. "
                         "The user supplied every dimension, position and material label.", "source_ids": []}],
        "questions": ["What loads, joints, material properties and site conditions must be checked "
                      "before this layout could become a fabrication design?"],
        "requirements": [{"id": "R1", "text": "Record the supplied part sizes and positions.",
                          "verification": "Compare the dimensioned sheets and parts table with the inputs.",
                          "source_ids": []}],
        "steps": [{"id": "A1", "title": "Review dimensions and placement",
                   "instructions": "Inspect each part sheet and the assembly views. Correct any input errors "
                   "with the part editor, then save a design or project and export its report.",
                   "depends_on": [], "source_ids": []}],
        "risks": [{"hazard": "A geometric layout does not establish strength or suitable connections.",
                   "mitigation": "Resolve the open engineering questions before relying on it for fabrication.",
                   "source_ids": []}],
        "checks": [{"requirement_id": "R1", "method": "Read back sizes and coordinates for every part.",
                    "expected": "All inputs match the exported parts table and dimensioned sheets."}],
        "parts": placed,
        "materials": [{"name": part["name"], "quantity": 1, "unit": "piece", "part_ids": [part["id"]],
                       "specification": "User-entered material: " + part["material"] +
                       "; refer to the parts table for current dimensions.", "source_ids": []} for part in placed],
        "calculations": [],
    }
    return normalized_document({
        "format": "fieldforge-blueprint", "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(), "model": "manual-layout; no AI model used",
        "request": request.__dict__, "design": design, "design_sha256": digest(design),
        "sources": [], "validation": {}, "review": None,
        "review_error": "No AI critique or independent engineering review has been performed.",
        "attempts": [], "status": "needs_revision",
    })
