import copy
import csv
import io
import json
from decimal import getcontext

import pytest
from blueprint_fixtures import document
from test_blueprints import references as references

from fieldforge.blueprints.__main__ import main
from fieldforge.blueprints.checks import check_design
from fieldforge.blueprints.engine import BlueprintRequest, digest, generate_blueprint
from fieldforge.blueprints.geometry import analyze_envelopes
from fieldforge.blueprints.geometry_report import geometry_csv
from fieldforge.blueprints.projects import (
    append_revision,
    checkout,
    create_project,
    head,
    load_project,
)
from fieldforge.blueprints.render import (
    export_blueprint,
    load_blueprint,
    normalized_document,
    save_blueprint,
)


def pair(position=(5, 5, 5), size=(10, 10, 10)):
    value = document("engineering")
    part = value["design"]["parts"][0]
    part.update(size_mm=[10, 10, 10], position_mm=[0, 0, 0])
    second = {**copy.deepcopy(part), "id": "P2", "position_mm": list(position), "size_mm": list(size)}
    value["design"]["parts"].append(second)
    value["design"]["materials"][0]["part_ids"].append("P2")
    value["design_sha256"] = digest(value["design"])
    return value


def limit(metric, value):
    return {"id": "G1", "label": "Geometry acceptance", "metric": "geometry." + metric,
            "target": "", "operator": "=", "value": value, "unit": "count"}


@pytest.mark.parametrize("position,relation,overlap,gap,groups", [
    ((5, 5, 5), "overlap", ["5", "5", "5"], ["0", "0", "0"], 1),
    ((10, 0, 0), "face_contact", ["0", "10", "10"], ["0", "0", "0"], 1),
    ((10, 10, 0), "edge_contact", ["0", "0", "10"], ["0", "0", "0"], 1),
    ((10, 10, 10), "point_contact", ["0", "0", "0"], ["0", "0", "0"], 1),
    ((13, 14, 10), "separated", ["0", "0", "0"], ["3", "4", "0"], 2),
    ((11, 0, 0), "separated", ["0", "10", "10"], ["1", "0", "0"], 2),
])
def test_all_pair_relations_and_exact_axes(position, relation, overlap, gap, groups):
    analysis = analyze_envelopes(pair(position)["design"]["parts"])
    assert len(analysis["pairs"]) == 1
    row = analysis["pairs"][0]
    assert {k: row[k] for k in ("part_ids", "relation", "overlap_mm", "gap_mm")} == {
        "part_ids": ["P1", "P2"], "relation": relation, "overlap_mm": overlap, "gap_mm": gap}
    assert row["clearance_mm"] == ("5" if gap == ["3", "4", "0"] else gap[0])
    assert not row["clearance_is_rounded"]
    assert analysis["summary"][relation + "_pairs"] == 1
    assert analysis["summary"]["connected_groups"] == groups


def test_containment_and_identical_envelopes_are_intersections():
    for position, size, expected in (((2, 3, 4), (1, 2, 3), ["1", "2", "3"]),
                                      ((0, 0, 0), (10, 10, 10), ["10"] * 3)):
        row = analyze_envelopes(pair(position, size)["design"]["parts"])["pairs"][0]
        assert row["relation"] == "overlap" and row["overlap_mm"] == expected


def test_decimal_boundaries_do_not_invent_overlap_or_tolerance():
    value = pair((0.3, 0, 0))["design"]["parts"]
    value[0].update(position_mm=[0.1, 0, 0], size_mm=[0.2, 10, 10])
    precision = getcontext().prec
    assert analyze_envelopes(value)["pairs"][0]["relation"] == "face_contact"
    value[1]["position_mm"][0] = 0.30000000000000004
    row = analyze_envelopes(value)["pairs"][0]
    assert row["relation"] == "separated" and row["gap_mm"][0] == "4E-17"
    value[1]["position_mm"][0] = 0.29999999999999993
    row = analyze_envelopes(value)["pairs"][0]
    assert row["relation"] == "overlap" and row["overlap_mm"][0] == "7E-17"
    assert getcontext().prec == precision


def test_smallest_positive_dimensions_at_large_origin_do_not_collapse():
    parts = pair((1000000, 0, 0))["design"]["parts"]
    for part in parts:
        part.update(position_mm=[1000000] * 3, size_mm=[5e-324] * 3)
    row = analyze_envelopes(parts)["pairs"][0]
    assert row["relation"] == "overlap" and row["overlap_mm"] == ["5E-324"] * 3


def test_order_and_translation_do_not_change_relations_or_groups():
    parts = pair((10, 0, 0))["design"]["parts"]
    parts += [{**copy.deepcopy(parts[0]), "id": "P3", "position_mm": [20, 0, 0]},
              {**copy.deepcopy(parts[0]), "id": "P4", "position_mm": [100, 100, 100]}]
    before = analyze_envelopes(parts)
    assert before["summary"]["groups"] == [["P1", "P2", "P3"], ["P4"]]
    for part in parts:
        part["position_mm"] = [v + 50000 for v in part["position_mm"]]
    assert analyze_envelopes(list(reversed(parts))) == before


@pytest.mark.parametrize("mutation", [
    lambda p: p.clear(), lambda p: p[1].update(id="P1"),
    lambda p: p[0].update(size_mm=[0, 1, 1]),
])
def test_incomplete_analysis_cannot_claim_clean_or_satisfy_geometry_limits(mutation):
    value = pair()
    mutation(value["design"]["parts"])
    analysis = analyze_envelopes(value["design"]["parts"])
    assert analysis["summary"]["status"] == "unresolved" and not analysis["pairs"]
    assert analysis["summary"]["connected_groups"] is None
    row = next(csv.DictReader(io.StringIO(geometry_csv(analysis))))
    assert row["analysis_status"] == "unresolved" and row["note"]
    result = check_design("engineering", value["design"], {"S1"}, [limit("overlap_pairs", 0)])
    assert result["acceptance"][0]["status"] == "unresolved"


def test_sixty_parts_analyze_every_pair_and_refuse_over_limit():
    parts = pair()["design"]["parts"][:1]
    parts = [{**copy.deepcopy(parts[0]), "id": f"P{i}"} for i in range(60)]
    result = analyze_envelopes(parts)
    assert len(result["pairs"]) == 1770
    assert result["summary"]["overlap_pairs"] == 1770
    assert result["summary"]["connected_groups"] == 1
    with pytest.raises(ValueError, match="item count"):
        analyze_envelopes(parts + [parts[0]])


def test_single_part_has_explicit_csv_status_and_one_group():
    analysis = analyze_envelopes(pair()["design"]["parts"][:1])
    assert analysis["summary"]["connected_groups"] == 1
    assert analysis["summary"]["overlap_pairs"] == 0
    rows = list(csv.DictReader(io.StringIO(geometry_csv(analysis))))
    assert len(rows) == 1 and rows[0]["analysis_status"] == "analyzed"
    assert rows[0]["part_a"] == "" and "One part" in rows[0]["note"]


@pytest.mark.parametrize("metric,position,expected,actual", [
    ("overlap_pairs", (5, 5, 5), 0, 1),
    ("connected_groups", (20, 0, 0), 1, 2),
    ("face_contact_pairs", (10, 10, 0), 1, 0),
])
def test_user_geometry_limits_block_but_geometry_observations_alone_are_warnings(metric, position, expected, actual):
    value = pair(position)
    assert normalized_document(value)["status"] == "draft"
    value["request"]["acceptance_rules"] = [limit(metric, expected)]
    normalized = normalized_document(value)
    assert normalized["status"] == "needs_revision"
    assert normalized["validation"]["acceptance"][0]["actual"] == actual
    assert normalized["validation"]["acceptance"][0]["status"] == "failed"


def test_geometry_is_recomputed_after_load_edit_export_and_project_checkout(tmp_path):
    value = pair()
    value["validation"]["geometry"] = {"overlap_pairs": 0, "status": "approved"}
    path = save_blueprint(value, tmp_path / "old.json")
    loaded = load_blueprint(path)
    assert loaded["validation"]["geometry"]["overlap_pairs"] == 1
    project_path = tmp_path / "geometry.ffproject.json"
    # Simulate an older hashed project with no geometry summary in its record.
    project = create_project(project_path, "Geometry", value)
    record = project["revisions"][0]
    record["blueprint"]["validation"].pop("geometry")
    record["checksum"] = digest({"project_id": project["id"], **{k: v for k, v in record.items() if k != "checksum"}})
    project_path.write_text(json.dumps(project), encoding="utf-8")
    snapshot = project_path.read_bytes()
    loaded_project = load_project(project_path)
    assert checkout(loaded_project)["validation"]["geometry"]["overlap_pairs"] == 1
    assert project_path.read_bytes() == snapshot
    value["design"]["parts"][1]["position_mm"] = [10, 0, 0]
    value["design_sha256"] = digest(value["design"])
    updated = append_revision(project_path, value, expected_head=head(loaded_project))
    assert updated["revisions"][0] == loaded_project["revisions"][0]
    target = export_blueprint(checkout(updated), tmp_path / "export")
    analysis = json.loads((target / "geometry.json").read_text(encoding="utf-8"))
    assert analysis["design_sha256"] == value["design_sha256"]
    assert analysis["summary"]["overlap_pairs"] == 0
    assert analysis["summary"]["face_contact_pairs"] == 1
    assert 'face contact' in (target / "report.html").read_text(encoding="utf-8")


def test_cli_geometry_works_without_database_model_or_network(tmp_path, capsys, monkeypatch):
    import socket

    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("Unexpected network access"))
    path = save_blueprint(pair((12, 0, 0)), tmp_path / "design.json")
    db = tmp_path / "never-created.db"
    assert main(["--database", str(db), "geometry", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["pairs"][0]["gap_mm"] == ["2", "0", "0"]
    assert not db.exists()
    for mode in ("project", "software"):
        source = save_blueprint(document(mode), tmp_path / (mode + ".json"))
        with pytest.raises(SystemExit) as exc:
            main(["geometry", str(source)])
        assert exc.value.code == 2


def test_geometry_limit_triggers_bounded_model_repair(references):
    calls = []

    class Client:
        def generate(self, _model, messages, **kwargs):
            calls.append(messages)
            value = pair()["design"] if len(calls) == 1 else pair((10, 0, 0))["design"]
            return json.dumps(value if len(calls) < 3 else {"findings": [], "missing_information": []}), False

    rules = [limit("overlap_pairs", 0)]
    result = generate_blueprint(references, BlueprintRequest("engineering", "Record inventory panels.",
                                acceptance_rules=rules), "fixture", Client())
    assert len(calls) == 3
    assert "Geometry acceptance" in calls[1][-1]["content"]
    assert result["validation"]["geometry"]["face_contact_pairs"] == 1
    assert result["status"] == "draft" and result["request"]["acceptance_rules"] == rules
