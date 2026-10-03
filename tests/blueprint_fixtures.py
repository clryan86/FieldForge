import copy

from fieldforge.blueprints.checks import check_design
from fieldforge.blueprints.engine import BlueprintRequest, digest
from fieldforge.blueprints.render import normalized_document


def revision(previous, request=None, instructions="Revise the recorded design."):
    before = normalized_document(copy.deepcopy(previous))
    value = copy.deepcopy(before)
    value["request"] = copy.deepcopy(request.__dict__ if request else before["request"])
    value["request"].update(revision_of=digest(before), revision_instructions=instructions)
    return value


def design(mode):
    value = {
        "title": "Example design", "summary": "A bounded design used to test the workflow.",
        "assumptions": [{"text": "Inputs supplied by the user need confirmation.", "source_ids": ["S1"]}],
        "questions": [],
        "requirements": [{"id": "R1", "text": "Keep a useful inventory.",
                          "verification": "Count recorded items.", "source_ids": ["S1"]}],
        "steps": [{"id": "A1", "title": "Prepare", "instructions": "Record the inventory.",
                   "depends_on": [], "source_ids": ["S1"]}],
        "risks": [{"hazard": "Incomplete information", "mitigation": "Review the source.",
                   "source_ids": ["S1"]}],
        "checks": [{"requirement_id": "R1", "method": "Inspect inventory.", "expected": "Complete record."}],
    }
    if mode == "engineering":
        value.update(
            parts=[{"id": "P1", "name": "Panel", "material": "User-specified material",
                    "size_mm": [1000, 500, 20], "position_mm": [0, 0, 0], "source_ids": ["S1"]}],
            materials=[{"name": "Panel", "quantity": 1, "unit": "piece",
                        "part_ids": ["P1"],
                        "specification": "1000 x 500 x 20 mm; no load rating asserted.",
                        "source_ids": ["S1"]}],
            calculations=[{"id": "C1", "formula": "rectangle_area_m2",
                           "inputs": [{"name": "length", "value": 1, "unit": "m"},
                                      {"name": "width", "value": 0.5, "unit": "m"}],
                           "source_ids": ["S1"]}],
        )
    elif mode == "project":
        value.update(
            phases=[{"id": "P1", "name": "Inventory", "duration_days": 2, "depends_on": [],
                     "deliverables": ["Inventory list"], "acceptance": "Items counted.",
                     "source_ids": ["S1"]},
                    {"id": "P2", "name": "Review", "duration_days": 3, "depends_on": ["P1"],
                     "deliverables": ["Review record"], "acceptance": "Record checked.",
                     "source_ids": ["S1"]}],
            resources=[{"name": "Coordinator", "quantity": 1, "unit": "person",
                        "availability": "Confirm before scheduling.", "source_ids": ["S1"]}],
        )
    else:
        value.update(
            components=[{"id": "UI", "name": "Inventory UI", "kind": "client",
                         "responsibility": "Record inventory.", "trust_zone": "device",
                         "data_stored": [], "source_ids": ["S1"]},
                        {"id": "DB", "name": "SQLite repository", "kind": "storage",
                         "responsibility": "Store inventory.", "trust_zone": "device",
                         "data_stored": ["Inventory"], "source_ids": ["S1"]}],
            connections=[{"source": "UI", "target": "DB", "protocol": "local repository API",
                          "data": "Inventory records", "authentication": "OS user permissions",
                          "source_ids": ["S1"]}],
            decisions=[{"choice": "Local persistence", "alternatives": ["Paper records"],
                        "rationale": "Offline lookup.", "source_ids": ["S1"]}],
        )
    return copy.deepcopy(value)


def document(mode):
    value = design(mode)
    request = BlueprintRequest(mode, "Record and review the inventory.")
    return {
        "format": "fieldforge-blueprint", "version": 1, "created_at": "2026-10-01T00:00:00Z",
        "model": "test-fixture", "request": request.__dict__, "design": value,
        "design_sha256": digest(value),
        "sources": [{"id": "S1", "title": "Inventory reference", "passage": "Keep an inventory.",
                     "source_url": "https://example.org/reference", "checksum": "0" * 64,
                     "license": "Test fixture"}],
        "validation": check_design(mode, value, {"S1"}),
        "review": {"findings": [], "missing_information": []}, "review_error": "",
        "attempts": [], "status": "draft",
    }
