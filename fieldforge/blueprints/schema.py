"""Bounded structured-output contracts; shared by the model and local validator."""

from __future__ import annotations

import math

MODES = {
    "engineering": "Engineering designs",
    "project": "Project plans and guides",
    "software": "Software and system architecture",
}


def text(maximum=2000):
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def number(minimum=0, maximum=1_000_000):
    return {"type": "number", "minimum": minimum, "maximum": maximum}


def array(item, maximum=30, minimum=0):
    return {"type": "array", "items": item, "minItems": minimum, "maxItems": maximum}


def obj(**properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


ID = {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,39}$",
      "minLength": 1, "maxLength": 40}
CITES = array(ID, 12)
POINT = {"type": "array", "items": number(), "minItems": 3, "maxItems": 3}


def blueprint_schema(mode):
    if mode not in MODES:
        raise ValueError("Unknown blueprint maker.")
    properties = dict(
        title=text(160), summary=text(3000),
        assumptions=array(obj(text=text(), source_ids=CITES), 20),
        questions=array(text(500), 20),
        requirements=array(obj(id=ID, text=text(), verification=text(), source_ids=CITES), 30, 1),
        steps=array(obj(id=ID, title=text(200), instructions=text(4000),
                        depends_on=array(ID), source_ids=CITES), 40, 1),
        risks=array(obj(hazard=text(), mitigation=text(), source_ids=CITES), 30, 1),
        checks=array(obj(requirement_id=ID, method=text(), expected=text()), 30, 1),
    )
    if mode == "engineering":
        properties.update(
            parts=array(obj(id=ID, name=text(160), material=text(160),
                            size_mm=POINT, position_mm=POINT, source_ids=CITES), 60),
            materials=array(obj(name=text(160), quantity=number(0.000001),
                                unit=text(40), specification=text(), part_ids=array(ID, 60),
                                source_ids=CITES), 60),
            calculations=array(obj(
                id=ID, formula={"type": "string", "enum": [
                    "rectangle_area_m2", "box_volume_liters", "dc_power_watts",
                    "battery_runtime_hours", "project_effort_hours"]},
                inputs=array(obj(name=text(80), value=number(), unit=text(40)), 8, 1),
                source_ids=CITES), 20),
        )
    elif mode == "project":
        properties.update(
            phases=array(obj(id=ID, name=text(160), duration_days=number(0.01, 3650),
                             depends_on=array(ID), deliverables=array(text(), 12, 1),
                             acceptance=text(), source_ids=CITES), 40, 1),
            resources=array(obj(name=text(160), quantity=number(0.000001), unit=text(40),
                                availability=text(), source_ids=CITES), 40),
        )
    else:
        properties.update(
            components=array(obj(id=ID, name=text(160), kind=text(80), responsibility=text(),
                                 trust_zone=text(80), data_stored=array(text(200), 20),
                                 source_ids=CITES), 30, 1),
            connections=array(obj(source=ID, target=ID, protocol=text(120),
                                  data=text(), authentication=text(),
                                  source_ids=CITES), 60),
            decisions=array(obj(choice=text(), alternatives=array(text(), 8, 1),
                                rationale=text(), source_ids=CITES), 20, 1),
        )
    return obj(**properties)


REVIEW_SCHEMA = obj(
    findings=array(obj(severity={"type": "string", "enum": ["blocking", "warning"]},
                       issue=text(), recommendation=text(), source_ids=CITES), 20),
    missing_information=array(text(), 20),
)


def validate(value, schema, path="$"):
    """Validate the deliberately small schema subset used above, without coercion."""
    import re

    kind = schema["type"]
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "number": type(value) in (int, float),
    }[kind]
    if not valid:
        raise ValueError(f"{path}: expected {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: unknown choice")
    if kind == "object":
        if set(value) != set(schema["properties"]):
            raise ValueError(f"{path}: missing or unexpected fields")
        for key, child in schema["properties"].items():
            validate(value[key], child, path + "." + key)
    elif kind == "array":
        if not schema["minItems"] <= len(value) <= schema["maxItems"]:
            raise ValueError(f"{path}: invalid item count")
        for index, item in enumerate(value):
            validate(item, schema["items"], f"{path}[{index}]")
    elif kind == "string":
        if (not value.strip() or not schema.get("minLength", 1) <= len(value) <= schema.get("maxLength", 2000)
                or "\x00" in value or any(ord(c) < 32 and c not in "\n\r\t" for c in value)):
            raise ValueError(f"{path}: invalid text")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise ValueError(f"{path}: invalid identifier")
    else:
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite or not schema["minimum"] <= value <= schema["maximum"]:
            raise ValueError(f"{path}: value must be finite and within bounds")
