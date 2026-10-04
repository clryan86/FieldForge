import copy
import json
import socket
from decimal import getcontext

import pytest
from blueprint_fixtures import document
from test_blueprint_clearance import limit
from test_blueprint_geometry import pair
from test_blueprints import references as references
from test_local_model import server as server

from fieldforge.blueprints.__main__ import main
from fieldforge.blueprints.constraints import analyze_constraints, require_consistent_rules
from fieldforge.blueprints.diagnostics import (
    design_feedback,
    diagnose_blueprint,
    repair_instructions,
)
from fieldforge.blueprints.engine import BlueprintRequest, generate_blueprint
from fieldforge.blueprints.render import save_blueprint
from fieldforge.knowledge.local_model import OllamaClient


def rules(*specs):
    return [limit(metric, value, operator, id=f"L{index}")
            for index, (metric, value, operator) in enumerate(specs, 1)]


@pytest.mark.parametrize("specs", [
    (("clearance", 5, ">="), ("clearance", 4.99999999, "<=")),
    (("gap_x", 5, "="), ("gap_x", 6, "=")),
    (("relation", "face_contact", "="), ("relation", "overlap", "=")),
    (("relation", "point_contact", "="), ("gap_z", 5e-324, ">=")),
    (("relation", "overlap", "="), ("clearance", 1, ">=")),
    (("relation", "separated", "="), ("clearance", 0, "=")),
    (("relation", "separated", "="), ("gap_x", 0, "="), ("gap_y", 0, "="), ("gap_z", 0, "=")),
    (("gap_x", 3, ">="), ("gap_y", 4, ">="), ("clearance", 4.999999999, "<=")),
    (("gap_x", 3, "<="), ("gap_y", 4, "<="), ("gap_z", 0, "="), ("clearance", 5.000000001, ">=")),
    (("gap_x", 5e-324, ">="), ("clearance", 0, "<=")),
])
def test_provable_pair_conflicts_use_exact_intervals_and_distance_identity(specs):
    limits = rules(*specs)
    limits[-1]["target"] = "P2/P1"  # Opposite target order must not hide a contradiction.
    original = copy.deepcopy(limits)
    precision = getcontext().prec
    result = analyze_constraints("engineering", limits)
    assert result["status"] == "conflicts_detected"
    assert result["conflicts"][0]["rule_ids"] == sorted(r["id"] for r in limits)
    assert result["conflicts"][0]["target"] == "P1/P2"
    assert analyze_constraints("engineering", list(reversed(limits))) == result
    assert getcontext().prec == precision and limits == original
    with pytest.raises(ValueError, match="Conflicting acceptance limits"):
        require_consistent_rules("engineering", limits)


@pytest.mark.parametrize("specs", [
    (("gap_x", 3, ">="), ("gap_y", 4, ">="), ("clearance", 5, "<=")),
    (("gap_x", 3, "<="), ("gap_y", 4, "<="), ("gap_z", 0, "="), ("clearance", 5, ">=")),
    (("relation", "face_contact", "="), ("clearance", 0, "=")),
    (("relation", "separated", "="), ("gap_x", 0, "=")),
    (("relation", "separated", "="), ("clearance", 5e-324, ">=")),
    (("clearance", 5, ">="), ("gap_x", 1, "<=")),  # Unbounded other axes may provide clearance.
    (("gap_x", 1e9, ">="), ("clearance", 1e9, "<=")),  # Coordinate feasibility is out of scope.
])
def test_compatible_or_unproven_limits_are_not_rejected(specs):
    result = require_consistent_rules("engineering", rules(*specs))
    assert not result["conflicts"] and result["status"] == "no_conflict_detected"
    assert "does not prove feasibility" in result["scope"]


def test_pair_groups_do_not_mix_and_legacy_numeric_epsilon_is_not_overridden():
    limits = rules(("clearance", 5, ">="), ("clearance", 4, "<="))
    limits[1]["target"] = "P1/P3"
    assert not analyze_constraints("engineering", limits)["conflicts"]
    limits = [{"id": f"L{i}", "label": "Size", "metric": "part.size_x", "target": "P1", "unit": "mm",
               "operator": op, "value": value} for i, (op, value) in enumerate(((">=", 5), ("<=", 4.99999999)))]
    result = require_consistent_rules("engineering", limits)
    assert result["not_analyzed_rule_ids"] == ["L0", "L1"] and result["examined_rule_ids"] == []


@pytest.mark.parametrize("mode,metric,target", [("engineering", "part.material", "P1"),
                                             ("software", "component.trust_zone", "DB")])
def test_text_conflicts_are_case_sensitive_and_grouped_by_metric_and_target(mode, metric, target):
    limits = [{"id": f"L{i}", "label": "Exact property", "metric": metric, "target": target,
               "unit": "text", "operator": "=", "value": value} for i, value in enumerate(("Local", "local"))]
    assert analyze_constraints(mode, limits)["conflicts"]
    limits[1]["value"] = "Local"
    assert not analyze_constraints(mode, limits)["conflicts"]
    limits[1].update(value="Other", target="OTHER")
    assert not analyze_constraints(mode, limits)["conflicts"]


def test_invalid_rules_are_rejected_before_diagnosis():
    invalid = [limit(unit="m")]
    with pytest.raises(ValueError, match="mm units"):
        analyze_constraints("engineering", invalid)
    with pytest.raises(ValueError, match="unique IDs"):
        analyze_constraints("engineering", [limit(), limit()])
    with pytest.raises(ValueError, match="supported"):
        analyze_constraints("software", [limit()])


def test_feedback_recomputes_measurements_and_preserves_exact_pair_data():
    value = pair((11, 10.000000001, 0))
    value["request"]["acceptance_rules"] = rules(("clearance", 1, "<="), ("relation", "separated", "="))
    value["validation"] = {"status": "draft", "acceptance": [{"status": "passed"}]}
    original = copy.deepcopy(value)
    result = diagnose_blueprint(value)
    assert value == original
    assert result["failing_rule_ids"] == ["L1"] and result["passing_rule_ids"] == ["L2"]
    assert result["acceptance"][0]["actual"] == "1" and result["acceptance"][0]["actual_is_rounded"]
    assert result["target_pairs"][0]["clearance_squared_mm2"] == "1.000000000000000001"
    assert {p["id"] for p in result["target_parts"]} == {"P1", "P2"}
    assert all("source_ids" not in p for p in result["target_parts"])
    assert result["design_sha256"] == value["design_sha256"] and len(result["request_sha256"]) == 64


def test_missing_pair_is_not_fabricated_and_all_three_modes_have_measured_feedback():
    value = document("engineering")
    value["request"]["acceptance_rules"] = [limit()]
    result = diagnose_blueprint(value)
    assert result["unresolved_rule_ids"] == ["C1"] and result["target_pairs"] == []
    assert [p["id"] for p in result["target_parts"]] == ["P1"]
    assert diagnose_blueprint(document("project"))["schedule"][-1]["end"] == 5
    assert "geometry" not in diagnose_blueprint(document("software"))


def test_feedback_marks_omitted_blocking_messages_without_omitting_acceptance_results():
    value = document("engineering")["design"]
    value["parts"] = [{**value["parts"][0], "id": f"P{i}", "size_mm": [0, 1, 1], "source_ids": ["MISSING"]}
                       for i in range(60)]
    result = design_feedback("engineering", value, {"S1"}, [limit()])
    assert len(result["blocking_issues"]) == 60 and result["blocking_issues_omitted"] > 0
    assert len(result["acceptance"]) == 1 and result["unresolved_rule_ids"] == ["C1"]


def test_repair_instructions_only_select_current_failures_and_keep_all_rules():
    value = pair((12, 0, 0))
    value["request"]["acceptance_rules"] = rules(("clearance", 5, ">="), ("relation", "separated", "="))
    result = diagnose_blueprint(value)
    text = repair_instructions(result, ["L1"])
    assert "L1" in text and "including passing rules" in text and len(text) < 4000
    for bad in ([], ["L2"], ["MISSING"], "L1", [None]):
        with pytest.raises(ValueError):
            repair_instructions(result, bad)
    value["request"]["acceptance_rules"].append(limit(value=1, operator="<=", id="CONFLICT"))
    with pytest.raises(ValueError, match="limits conflict"):
        repair_instructions(diagnose_blueprint(value), ["L1"])


def test_conflicts_stop_generation_before_retrieval_or_any_model_call(references, monkeypatch):
    monkeypatch.setattr("fieldforge.blueprints.engine.retrieve_blueprint_evidence",
                        lambda *_a, **_kw: pytest.fail("Retrieval should not run for conflicting limits"))
    request = BlueprintRequest("engineering", "Record the inventory.",
                               acceptance_rules=rules(("clearance", 5, ">="), ("clearance", 1, "<=")))
    with pytest.raises(ValueError, match="L1, L2"):
        generate_blueprint(references, request, "unused", None)


def test_first_revision_and_repair_receive_current_measurements_over_real_transport(references, server):
    previous = pair((12, 0, 0))
    previous["request"]["acceptance_rules"] = [limit(value=1)]  # Originally passing, now a stricter user request.
    original = copy.deepcopy(previous)
    request = BlueprintRequest("engineering", "Record the inventory.", acceptance_rules=[limit(value=5)])
    calls = []

    def reply():
        payload = copy.deepcopy(server.requests[-1][1])
        calls.append(payload)
        response = (previous["design"] if len(calls) == 1 else pair((15, 0, 0))["design"]
                    if len(calls) == 2 else {"findings": [], "missing_information": []})
        return {"done": True, "message": {"role": "assistant", "content": json.dumps(response)}}

    server.responses["/api/chat"] = reply
    result = generate_blueprint(references, request, "example:small", OllamaClient(port=server.port, timeout=10),
                                previous=previous, instructions="Address the measured clearance failure.")
    assert len(calls) == 3 and previous == original
    initial = json.loads(calls[0]["messages"][1]["content"])
    feedback = initial["deterministic_feedback"]
    assert feedback["acceptance"][0]["actual"] == "2" and feedback["acceptance"][0]["value"] == 5
    assert feedback["failing_rule_ids"] == ["C1"]
    repair = json.loads(calls[1]["messages"][-1]["content"])
    assert repair["deterministic_feedback"]["target_pairs"][0]["clearance_mm"] == "2"
    assert not repair["validation_errors_truncated"]
    critique = json.loads(calls[2]["messages"][-1]["content"])
    assert critique["deterministic_feedback"]["passing_rule_ids"] == ["C1"]
    assert result["status"] == "draft" and result["request"]["acceptance_rules"] == [limit(value=5)]
    assert "PRIVATE DATA" not in json.dumps(calls)


def test_schema_invalid_repair_has_no_invented_measurements(references):
    calls = []

    class Client:
        def generate(self, _model, messages, **_kwargs):
            calls.append(copy.deepcopy(messages))
            value = ({"title": "incomplete"} if len(calls) == 1 else document("software")["design"]
                     if len(calls) == 2 else {"findings": [], "missing_information": []})
            return json.dumps(value), False

    generate_blueprint(references, BlueprintRequest("software", "Record the inventory."), "fixture", Client())
    repair = json.loads(calls[1][-1]["content"])
    assert repair["deterministic_feedback"] is None
    assert repair["validation_errors"]


def test_diagnose_and_preflight_cli_are_offline_readonly_and_have_failure_exit_codes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(socket, "socket", lambda *_a, **_kw: pytest.fail("Network called"))
    value = pair((12, 0, 0))
    value["request"]["acceptance_rules"] = [limit()]
    source = save_blueprint(value, tmp_path / "design.json")
    original = source.read_bytes()
    db = tmp_path / "not-created.db"
    assert main(["--database", str(db), "diagnose", str(source)]) == 1
    assert json.loads(capsys.readouterr().out)["failing_rule_ids"] == ["C1"]
    path = tmp_path / "limits.json"
    path.write_text(json.dumps(rules(("clearance", 5, ">="), ("clearance", 1, "<="))), encoding="utf-8")
    assert main(["--database", str(db), "limits-check", "engineering", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["conflicts"]
    path.write_text("[]", encoding="utf-8")
    assert main(["limits-check", "engineering", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "no_conflict_detected"
    assert not db.exists() and source.read_bytes() == original
