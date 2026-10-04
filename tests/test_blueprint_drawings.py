import copy
import csv
import io
import xml.etree.ElementTree as ET

import pytest
from blueprint_fixtures import document

from fieldforge.blueprints.acceptance import evaluate_rules
from fieldforge.blueprints.engine import digest
from fieldforge.blueprints.engineering import bounds, schedule_csvs
from fieldforge.blueprints.render import drawings, export_blueprint, load_blueprint, report_html


def assembly(count=4):
    value = document("engineering")
    value["design"]["parts"] = [
        {"id": f"P{i + 1}", "name": f"Panel {i + 1}", "material": "Prototype material",
         "size_mm": [1000, 500, 20], "position_mm": [0, 0, i * 200], "source_ids": ["S1"]}
        for i in range(count)
    ]
    value["design"]["materials"][0].update(quantity=count or 1,
                                            part_ids=[p["id"] for p in value["design"]["parts"]])
    value["design_sha256"] = digest(value["design"])
    return value


def texts(svg):
    return [node.text for node in ET.fromstring(svg) if node.tag.endswith("}text")]


def geometry(svg):
    return [node.attrib for node in ET.fromstring(svg) if "data-part" in node.attrib]


def measured_value(design, metric):
    rule = {"id": "L1", "label": "Dimension check", "metric": metric, "target": "",
            "operator": ">=", "value": 0, "unit": "mm"}
    return evaluate_rules("engineering", design, [rule], [])[0]["actual"]


def test_assembly_dimensions_exclude_unused_origin_and_match_acceptance():
    original = assembly()
    translated = copy.deepcopy(original)
    for part in translated["design"]["parts"]:
        part["position_mm"] = [v + 40000 for v in part["position_mm"]]
    before, after = drawings(original), drawings(translated)
    for name in ("top.svg", "front.svg", "side.svg", "isometric.svg", "part-001.svg"):
        assert geometry(before[name]) == geometry(after[name])
    assert "X: 1000 mm" in texts(after["top.svg"])
    assert "Y: 500 mm" in texts(after["top.svg"])
    assert "Z: 620 mm" in texts(after["front.svg"])
    assert bounds(translated["design"]["parts"]) == ([40000, 40000, 40000], [1000, 500, 620])
    assert measured_value(translated["design"], "envelope.z") == 620


def test_small_part_at_large_origin_preserves_recorded_dimension():
    value = assembly(1)
    part = value["design"]["parts"][0]
    part.update(position_mm=[1000000] * 3, size_mm=[1e-12, 0.12345678901234, 1000])
    assert bounds([part])[1] == part["size_mm"]
    assert measured_value(value["design"], "envelope.x") == 1e-12
    svg = drawings(value)["part-001.svg"]
    assert "X: 1e-12 mm" in texts(svg)
    assert "Y: 0.12345678901234 mm" in texts(svg)
    assert "XYZ size: 1e-12 × 0.12345678901234 × 1000 mm" in texts(svg)


@pytest.mark.parametrize("count", [0, 1, 60])
def test_sheets_are_bounded_complete_parseable_and_deterministic(count):
    value = assembly(count)
    images = drawings(value)
    assert images == drawings(value)
    assert len(images) == count + 4
    assert len(geometry(images["isometric.svg"])) == count * 6
    for name, image in images.items():
        root = ET.fromstring(image)
        assert root.attrib["viewBox"] == "0 0 1100 780"
        assert root.find("{http://www.w3.org/2000/svg}desc").text
        assert "<script" not in image
        if name.startswith("part-"):
            assert len(geometry(image)) == 3
            assert "ONE INSTANCE" in image
    assert all(f"part-{i:03d}.svg" in images for i in range(1, count + 1))


def test_zero_dimensions_remain_a_visible_draft_without_invalid_geometry(tmp_path):
    value = assembly(1)
    value["design"]["parts"][0]["size_mm"] = [0, 0, 0]
    value["design_sha256"] = digest(value["design"])
    target = export_blueprint(value, tmp_path / "zero")
    assert load_blueprint(target / "blueprint.json")["status"] == "needs_revision"
    for svg in target.glob("*.svg"):
        text = svg.read_text(encoding="utf-8")
        ET.fromstring(text)
        assert "nan" not in text and "inf" not in text
    assert "X: 0 mm" in texts((target / "part-001.svg").read_text(encoding="utf-8"))


def test_export_schedules_preserve_instances_units_precision_and_source_links(tmp_path):
    value = assembly(3)
    value["design"]["parts"][0]["size_mm"][0] = 1000.123456789
    value["design"]["materials"][0].update(quantity=2.75, unit="square metre")
    value["design_sha256"] = digest(value["design"])
    before = copy.deepcopy(value)
    target = export_blueprint(value, tmp_path / "sheets")
    assert value == before
    with (target / "parts.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 3
    assert rows[0]["size_x_mm"] == "1000.123456789"
    assert [r["part_id"] for r in rows] == ["P1", "P2", "P3"]
    assert all(r["instances"] == "1" and r["source_ids"] == "S1" for r in rows)
    assert all((target / r["sheet"]).is_file() for r in rows)
    with (target / "materials.csv").open(encoding="utf-8", newline="") as source:
        material = next(csv.DictReader(source))
    assert material["quantity"] == "2.75" and material["unit"] == "square metre"
    assert material["part_ids"] == "P1; P2; P3"
    assert load_blueprint(target / "blueprint.json")["design"] == value["design"]
    report = (target / "report.html").read_text(encoding="utf-8")
    assert '<caption>Parts</caption>' in report and '<th scope="col">' in report
    assert 'id="drawing-part-003.svg"' in report and 'href="#drawing-part-003.svg"' in report


@pytest.mark.parametrize("text", ['=1+1', '  +SUM(1,2)', '\t@SUM(1,2)', '-2+3', '\rhello', '\nhello'])
def test_csv_formula_like_text_is_inert_without_mutating_original(text):
    value = assembly(1)
    value["design"]["parts"][0]["name"] = text
    value["design"]["materials"][0]["specification"] = text
    for name, key in (("parts.csv", "name"), ("materials.csv", "specification")):
        row = next(csv.DictReader(io.StringIO(schedule_csvs(value["design"])[name], newline="")))
        assert row[key] == "'" + text
    assert value["design"]["parts"][0]["name"] == text


def test_model_text_is_escaped_in_sheets_and_tables_and_csv_roundtrips():
    value = assembly(1)
    text = '<script>alert("bad")</script>,\nsecond line'
    value["design"]["parts"][0]["name"] = text
    value["design_sha256"] = digest(value["design"])
    assert '<script>' not in report_html(value)
    svg = drawings(value)["part-001.svg"]
    assert '<script>' not in svg
    assert text in ET.fromstring(svg).find('{http://www.w3.org/2000/svg}desc').text
    row = next(csv.DictReader(io.StringIO(schedule_csvs(value["design"])["parts.csv"], newline="")))
    assert row["name"] == text


@pytest.mark.parametrize("mode", ["project", "software"])
def test_other_makers_do_not_get_engineering_schedules(mode, tmp_path):
    target = export_blueprint(document(mode), tmp_path / mode)
    assert not list(target.glob("*.csv"))
    assert "Parts and materials schedules" not in (target / "report.html").read_text(encoding="utf-8")
