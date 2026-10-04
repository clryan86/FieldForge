import copy
import json

import pytest
from blueprint_fixtures import design, document
from test_blueprints import references as references
from test_local_model import server as server

from fieldforge.blueprints.__main__ import main, read_limits
from fieldforge.blueprints.acceptance import METRICS, validate_rules
from fieldforge.blueprints.checks import check_design
from fieldforge.blueprints.engine import BlueprintRequest, generate_blueprint
from fieldforge.blueprints.projects import (
    checkout,
    create_project,
    head,
    load_project,
    restore_revision,
)
from fieldforge.blueprints.render import (
    load_blueprint,
    normalized_document,
    report_html,
    save_blueprint,
)
from fieldforge.knowledge.local_model import OllamaClient


def limit(metric, value, target="", operator="=", **extra):
    return {"id": "L1", "label": "User acceptance limit", "metric": metric,
            "target": target, "operator": operator, "value": value, "unit": METRICS[metric][1], **extra}


@pytest.mark.parametrize("mode,metric,value,target", [
    ("engineering", "envelope.x", 1000, ""),
    ("engineering", "envelope.y", 500, ""),
    ("engineering", "envelope.z", 20, ""),
    ("engineering", "part.size_x", 1000, "P1"),
    ("engineering", "part.size_y", 500, "P1"),
    ("engineering", "part.size_z", 20, "P1"),
    ("engineering", "part.material", "User-specified material", "P1"),
    ("engineering", "part.count", 1, ""),
    ("project", "project.duration", 5, ""),
    ("project", "phase.duration", 3, "P2"),
    ("project", "phase.finish", 5, "P2"),
    ("software", "component.count", 2, ""),
    ("software", "component.exists", 1, "DB"),
    ("software", "component.kind", "storage", "DB"),
    ("software", "component.trust_zone", "device", "DB"),
    ("project", "requirement.exists", 1, "R1"),
    ("software", "step.exists", 1, "A1"),
])
def test_all_supported_measurements(mode, metric, value, target):
    result = check_design(mode, design(mode), {"S1"}, [limit(metric, value, target)])
    assert result["acceptance"][0]["actual"] == value
    assert result["acceptance"][0]["status"] == "passed"
    assert result["status"] == "draft"


def test_extent_is_translation_invariant_and_deadline_is_critical_path():
    value = design("engineering")
    value["parts"][0]["position_mm"] = [200, 30, 50]
    second = copy.deepcopy(value["parts"][0])
    second.update(id="P2", position_mm=[1500, 30, 50])
    value["parts"].append(second)
    result = check_design("engineering", value, {"S1"}, [limit("envelope.x", 2300)])
    assert result["acceptance"][0]["status"] == "passed"
    parallel = design("project")
    parallel["phases"][1]["depends_on"] = []
    result = check_design("project", parallel, {"S1"}, [limit("project.duration", 3)])
    assert result["acceptance"][0]["status"] == "passed"
    parallel["phases"][0]["depends_on"] = ["P2"]
    parallel["phases"][1]["depends_on"] = ["P1"]
    result = check_design("project", parallel, {"S1"}, [limit("project.duration", 5)])
    assert result["acceptance"][0]["status"] == "unresolved"
    assert result["status"] == "needs_revision"


@pytest.mark.parametrize("metric,target", [("part.size_x", "Gone"), ("part.size_x", "P1"), ("requirement.exists", "Gone")])
def test_missing_and_ambiguous_ids_cannot_pass(metric, target):
    value = design("engineering")
    value["parts"].append(copy.deepcopy(value["parts"][0]))
    result = check_design("engineering", value, {"S1"}, [limit(metric, 1, target)])
    assert result["acceptance"][0]["status"] == "unresolved"
    assert result["status"] == "needs_revision"


def test_conflicting_limits_fail_and_numeric_comparison_absorbs_only_roundoff():
    rules = [limit("envelope.x", 900, operator="<="), limit("envelope.x", 1100, operator=">=", id="L2")]
    result = check_design("engineering", design("engineering"), {"S1"}, rules)
    assert [r["status"] for r in result["acceptance"]] == ["failed", "failed"]
    value = design("project")
    value["phases"][0]["duration_days"] = 0.1
    value["phases"][1]["duration_days"] = 0.2
    result = check_design("project", value, {"S1"}, [limit("project.duration", 0.3)])
    assert result["acceptance"][0]["status"] == "passed"
    result = check_design("engineering", design("engineering"), {"S1"}, [limit("envelope.x", 999.999, operator="<=")])
    assert result["acceptance"][0]["status"] == "failed"


@pytest.mark.parametrize("change", [
    {"value": True}, {"value": float("nan")}, {"value": float("inf")}, {"value": 10**400},
    {"value": -1}, {"operator": "eval"}, {"target": "__import__('os')"}, {"unit": "m"},
    {"metric": "project.duration"}, {"target": "P1"}, {"label": ""}, {"extra": 1},
])
def test_invalid_rules_rejected_before_generation(change):
    rule = limit("envelope.x", 1000)
    rule.update(change)
    with pytest.raises(ValueError):
        BlueprintRequest("engineering", "Design a storage rack.", acceptance_rules=[rule])


def test_text_retention_and_collection_bounds():
    for bad in ([limit("component.trust_zone", "device", "DB", "<=")],
                [limit("component.trust_zone", "\0", "DB")],
                [limit("component.exists", 0, "DB")],
                [limit("component.exists", 1, "DB")] * 2,
                [limit("component.exists", 1, "DB")] * 31, None):
        with pytest.raises(ValueError):
            validate_rules("software", bad)
    result = check_design("software", design("software"), {"S1"}, [limit("component.trust_zone", "Device", "DB")])
    assert result["acceptance"][0]["status"] == "failed"


def test_fixed_limits_trigger_real_transport_repair_and_survive_optimistic_critique(server, references):
    rules = [limit("envelope.x", 600, operator="<=")]
    request = BlueprintRequest("engineering", "Record the inventory.", acceptance_rules=rules)
    calls = []

    def reply():
        payload = server.requests[-1][1]
        calls.append(payload)
        result = design("engineering") if len(calls) <= 2 else {"findings": [], "missing_information": []}
        # A caller changing the original list while the model runs cannot relax the snapshot.
        rules[0]["value"] = 1000
        return {"done": True, "message": {"role": "assistant", "content": json.dumps(result)}}

    server.responses["/api/chat"] = reply
    value = generate_blueprint(references, request, "example:small", OllamaClient(port=server.port, timeout=10))
    assert len(calls) == 3
    assert "Acceptance L1" in calls[1]["messages"][-1]["content"]
    assert value["request"]["acceptance_rules"][0]["value"] == 600
    assert value["validation"]["acceptance"][0]["status"] == "failed"
    assert value["status"] == "needs_revision"
    assert json.loads(calls[2]["messages"][-1]["content"])["validation"]["acceptance"][0]["actual"] == 1000


def test_model_can_repair_dimensions_but_cannot_rewrite_limits(references):
    class Client:
        calls = 0

        def generate(self, _model, messages, **_kwargs):
            self.calls += 1
            value = design("engineering")
            if self.calls == 2:
                value["parts"][0]["size_mm"][0] = 600
            if self.calls == 3:
                value = {"findings": [], "missing_information": []}
            return json.dumps(value), False

    request = BlueprintRequest("engineering", "Record the inventory.", acceptance_rules=[limit("envelope.x", 600, operator="<=")])
    value = generate_blueprint(references, request, "local", Client())
    assert value["status"] == "draft"
    assert value["validation"]["acceptance"][0]["actual"] == 600
    assert len(value["attempts"]) == 2


def test_saved_rules_recompute_and_project_restore_preserves_them(tmp_path):
    value = document("engineering")
    value["request"]["acceptance_rules"] = [limit("envelope.x", 600, operator="<=", label="Width <script>bad</script>")]
    value["validation"] = {"status": "draft", "acceptance": [{"status": "passed"}]}
    path = save_blueprint(value, tmp_path / "limited.json")
    loaded = load_blueprint(path)
    assert loaded["validation"]["acceptance"][0]["status"] == "failed"
    assert loaded["status"] == "needs_revision"
    assert "&lt;script&gt;" in report_html(loaded) and "<script>" not in report_html(loaded)
    project_path = tmp_path / "limited.ffproject.json"
    project = create_project(project_path, "Limited design", loaded)
    restore_revision(project_path, 1, expected_head=head(project))
    assert checkout(load_project(project_path))["request"]["acceptance_rules"] == value["request"]["acceptance_rules"]
    old = document("software")
    del old["request"]["acceptance_rules"]
    assert normalized_document(old) == old


def test_limits_cli_is_offline_and_has_useful_exit_codes(tmp_path, capsys):
    source = save_blueprint(document("project"), tmp_path / "design.json")
    rules = tmp_path / "limits.json"
    rules.write_text(json.dumps([limit("project.duration", 4, operator="<=")]), encoding="utf-8")
    database = tmp_path / "no-database.db"
    prefix = ["--database", str(database)]
    assert main(prefix + ["acceptance-metrics", "project"]) == 0
    assert "project.duration" in json.loads(capsys.readouterr().out)
    assert main(prefix + ["check", str(source)]) == 0
    capsys.readouterr()
    output = tmp_path / "report"
    assert main(prefix + ["apply-limits", str(source), str(rules), str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "needs_revision"
    assert main(prefix + ["check", str(output / "blueprint.json")]) == 1
    assert json.loads(capsys.readouterr().out)["validation"]["acceptance"][0]["actual"] == 5
    assert not database.exists()
    assert load_blueprint(source)["request"]["acceptance_rules"] == []
    rules.write_text('[{"id":"L1","id":"L2"}]')
    with pytest.raises(ValueError, match="Duplicate"):
        read_limits(rules, "project")
    rules.write_bytes(b" " * 65_537)
    with pytest.raises(ValueError, match="64 KiB"):
        read_limits(rules, "project")


def test_cli_refinement_inherits_limits_until_explicitly_replaced(tmp_path, monkeypatch, capsys):
    value = document("engineering")
    rules = [limit("envelope.x", 600, operator="<=")]
    value["request"]["acceptance_rules"] = rules
    source = save_blueprint(value, tmp_path / "limited.json")
    captured = []

    def generate(_library, request, *_args, **_kwargs):
        captured.append(copy.deepcopy(request.acceptance_rules))
        result = document("engineering")
        result["request"] = copy.deepcopy(request.__dict__)
        return normalized_document(result)

    monkeypatch.setattr("fieldforge.blueprints.__main__.generate_blueprint", generate)
    prefix = ["--database", str(tmp_path / "library.db"), "refine", str(source),
              "Use the recorded limits.", "--model", "fixture"]
    assert main(prefix + ["--output", str(tmp_path / "inherited")]) == 0
    capsys.readouterr()
    assert captured[-1] == rules
    cleared = tmp_path / "cleared.json"
    cleared.write_text("[]")
    assert main(prefix + ["--limits", str(cleared), "--output", str(tmp_path / "cleared")]) == 0
    capsys.readouterr()
    assert captured[-1] == []
    assert load_blueprint(source)["request"]["acceptance_rules"] == rules
