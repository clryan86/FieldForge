import copy
import csv
import json
from decimal import getcontext

import pytest
from test_blueprint_geometry import pair
from test_blueprints import references as references

from fieldforge.blueprints.__main__ import main
from fieldforge.blueprints.acceptance import evaluate_rules, validate_rules
from fieldforge.blueprints.checks import check_design
from fieldforge.blueprints.engine import BlueprintRequest, digest, generate_blueprint
from fieldforge.blueprints.geometry import analyze_envelopes
from fieldforge.blueprints.projects import (
    append_revision,
    checkout,
    create_project,
    head,
    restore_revision,
)
from fieldforge.blueprints.render import (
    export_blueprint,
    load_blueprint,
    normalized_document,
    save_blueprint,
)


def limit(metric="clearance", value=5, operator=">=", target="P1/P2", **extra):
    return {"id": "C1", "label": "Required pair clearance", "metric": "pair." + metric,
            "value": value, "operator": operator, "target": target,
            "unit": "text" if metric == "relation" else "mm", **extra}


def evaluated(value, rule):
    return check_design("engineering", value["design"], {"S1"}, [rule])["acceptance"][0]


@pytest.mark.parametrize("metric,value,actual", [
    ("clearance", 5, "5"), ("gap_x", 3, "3"), ("gap_y", 4, "4"),
    ("gap_z", 0, "0"), ("relation", "separated", "separated"),
])
def test_pair_measurements_are_symmetric_and_use_exact_recorded_units(metric, value, actual):
    document = pair((13, 14, 0))
    for target in ("P1/P2", "P2/P1"):
        row = evaluated(document, limit(metric, value, "=", target))
        assert row["actual"] == actual and row["status"] == "passed"
    if metric == "clearance":
        assert row["actual_squared_mm2"] == "25" and not row["actual_is_rounded"]


@pytest.mark.parametrize("position,relation", [
    ((5, 5, 5), "overlap"), ((10, 0, 0), "face_contact"),
    ((10, 10, 0), "edge_contact"), ((10, 10, 10), "point_contact"),
])
def test_zero_clearance_does_not_assert_a_specific_kind_of_contact(position, relation):
    value = pair(position)
    assert evaluated(value, limit(value=0, operator="="))["status"] == "passed"
    assert evaluated(value, limit("relation", relation, "="))["status"] == "passed"
    assert evaluated(value, limit("relation", "separated", "="))["status"] == "failed"


@pytest.mark.parametrize("metric", ["gap_x", "clearance"])
def test_pair_limits_do_not_inherit_legacy_arithmetic_epsilon(metric):
    value = pair((10.99999999, 0, 0))
    row = evaluated(value, limit(metric, 1))
    assert row["status"] == "failed" and row["actual"] == "0.99999999"
    assert evaluated(value, limit(metric, 1, "<="))["status"] == "passed"


def test_rounded_display_cannot_make_a_failed_distance_limit_pass():
    value = pair((11, 10.000000001, 0))
    row = evaluated(value, limit(value=1, operator="<="))
    assert row["actual"] == "1" and row["actual_is_rounded"]
    assert row["actual_squared_mm2"] == "1.000000000000000001"
    assert row["status"] == "failed" and "squared distances exactly" in row["detail"]
    assert evaluated(value, limit(value=1, operator="="))["status"] == "failed"
    assert evaluated(value, limit(value=1, operator=">="))["status"] == "passed"


def test_irrational_clearance_and_smallest_finite_gap_avoid_float_underflow():
    value = pair((11, 11, 0))
    assert evaluated(value, limit(value=1.414213562373095))["status"] == "passed"
    assert evaluated(value, limit(value=1.4142135623730951))["status"] == "failed"
    value["design"]["parts"][0]["size_mm"][0] = 5e-324
    value["design"]["parts"][1]["position_mm"] = [1e-323, 0, 0]
    precision = getcontext().prec
    row = evaluated(value, limit(value=5e-324, operator="="))
    assert row["actual"] == "5E-324" and row["actual_squared_mm2"] == "2.5E-647"
    assert row["status"] == "passed" and getcontext().prec == precision


@pytest.mark.parametrize("target", ["P1", "P1/P1", "/P2", "P1/", "P1/P2/P3", "P1 /P2", "P1\\P2", "P1/<script>"])
def test_malformed_pair_targets_are_rejected(target):
    with pytest.raises(ValueError, match="distinct part IDs"):
        validate_rules("engineering", [limit(target=target)])


@pytest.mark.parametrize("change", [
    {"metric": "pair.unknown"}, {"unit": "m"}, {"value": -1}, {"value": float("nan")},
    {"value": True}, {"operator": "eval"},
])
def test_malformed_pair_numeric_rules_are_rejected(change):
    with pytest.raises(ValueError):
        validate_rules("engineering", [limit(**change)])


def test_relation_values_are_bounded_and_other_makers_cannot_use_pair_rules():
    for value in ("Face contact", "connected", "approved", "<script>"):
        with pytest.raises(ValueError):
            validate_rules("engineering", [limit("relation", value, "=")])
    for mode in ("project", "software"):
        with pytest.raises(ValueError):
            validate_rules(mode, [limit()])


@pytest.mark.parametrize("change", [
    lambda p: p.pop(), lambda p: p[1].update(id="P1"),
    lambda p: p[0].update(size_mm=[0, 10, 10]), lambda p: p[1].update(id="RENAMED"),
])
def test_missing_ambiguous_and_degenerate_targets_are_unresolved(change):
    value = pair()
    change(value["design"]["parts"])
    row = evaluated(value, limit(value=0))
    assert row["status"] == "unresolved" and row["actual"] is None


def test_standalone_rule_evaluation_computes_fresh_geometry_once(monkeypatch):
    import fieldforge.blueprints.acceptance as acceptance

    calls = []
    original = acceptance.analyze_envelopes

    def track(parts):
        calls.append(parts)
        return original(parts)

    monkeypatch.setattr(acceptance, "analyze_envelopes", track)
    rules = [limit(id=f"L{i}") for i in range(30)]
    rows = evaluate_rules("engineering", pair((13, 14, 0))["design"], rules, [])
    assert len(calls) == 1 and all(row["status"] == "passed" for row in rows)


def test_clearances_export_recompute_and_survive_revision_restore(tmp_path):
    value = pair((13, 14, 0))
    value["request"]["acceptance_rules"] = [limit()]
    value["validation"]["acceptance"] = [{"status": "approved", "actual": 5000}]
    path = save_blueprint(value, tmp_path / "design.json")
    assert load_blueprint(path)["validation"]["acceptance"][0]["actual"] == "5"
    project_path = tmp_path / "clearance.ffproject.json"
    project = create_project(project_path, "Clearance", value)
    revised = copy.deepcopy(value)
    revised["design"]["parts"][1]["position_mm"] = [12, 0, 0]
    revised["design_sha256"] = digest(revised["design"])
    project = append_revision(project_path, revised, expected_head=head(project))
    assert checkout(project)["validation"]["acceptance"][0]["status"] == "failed"
    restored = restore_revision(project_path, 1, expected_head=head(project))
    assert checkout(restored)["validation"]["acceptance"][0]["status"] == "passed"
    target = export_blueprint(checkout(restored), tmp_path / "export")
    with (target / "geometry.csv").open(encoding="utf-8", newline="") as f:
        row = next(csv.DictReader(f))
    assert row["clearance_mm"] == "5" and row["clearance_squared_mm2"] == "25"
    report = (target / "report.html").read_text(encoding="utf-8")
    assert "Acceptance results" in report and "P1/P2" in report
    assert report.index("Acceptance results") < report.index("Drawing sheets")


def test_pair_limits_cli_apply_check_and_repair_preserve_both_target_ids(tmp_path, capsys, references):
    value = pair((12, 0, 0))
    source = save_blueprint(value, tmp_path / "source.json")
    limits = tmp_path / "limits.json"
    limits.write_text(json.dumps([limit()]), encoding="utf-8")
    db = tmp_path / "never-created.db"
    assert main(["--database", str(db), "apply-limits", str(source), str(limits), str(tmp_path / "applied")]) == 0
    assert main(["check", str(tmp_path / "applied" / "blueprint.json")]) == 1
    assert not db.exists()
    assert "P1/P2" in capsys.readouterr().out
    calls = []

    class Client:
        def generate(self, _model, messages, **kwargs):
            calls.append(messages)
            result = value["design"] if len(calls) == 1 else pair((13, 14, 0))["design"]
            return json.dumps(result if len(calls) < 3 else {"findings": [], "missing_information": []}), False

    request = BlueprintRequest("engineering", "Record the inventory panel positions.", acceptance_rules=[limit()])
    result = generate_blueprint(references, request, "fixture", Client())
    assert len(calls) == 3 and "P1/P2" in calls[1][-1]["content"]
    assert result["status"] == "draft" and result["request"]["acceptance_rules"] == [limit()]
    assert result["validation"]["acceptance"][0]["actual"] == "5"


def test_minimum_clearance_can_fail_despite_favorable_review():
    value = pair((12, 0, 0))
    value["request"]["acceptance_rules"] = [limit()]
    assert normalized_document(value)["status"] == "needs_revision"
    assert analyze_envelopes(value["design"]["parts"])["pairs"][0]["clearance_mm"] == "2"
