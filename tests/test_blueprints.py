import copy
import json
import threading
import xml.etree.ElementTree as ET

import pytest
from blueprint_fixtures import design, document
from test_assistant import server as server

from fieldforge.blueprints.checks import check_design
from fieldforge.blueprints.engine import BlueprintRequest, digest, generate_blueprint
from fieldforge.blueprints.render import (
    drawings,
    export_blueprint,
    load_blueprint,
    report_html,
    save_blueprint,
)
from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary
from fieldforge.knowledge.assistant import GenerationCancelled, LocalModelError, OllamaClient


@pytest.fixture
def references(tmp_path):
    lib = KnowledgeLibrary(tmp_path / "library.db")
    lib.upsert(KnowledgeArticle("inventory", "Inventory", "Record and review the inventory. "
                               "Account for every item, review its state, and preserve the records.",
                               "projects"))
    lib.annotate("inventory", bookmarked=True, note="PRIVATE DATA NEVER SEND")
    return lib


@pytest.mark.parametrize("mode", ["engineering", "project", "software"])
def test_three_makers_use_real_structured_transport_and_export(mode, server, references, tmp_path):
    response = design(mode)
    review = {"findings": [], "missing_information": []}
    calls = []

    def reply():
        payload = server.requests[-1][1]
        calls.append(payload)
        value = response if len(calls) == 1 else review
        return {"done": True, "message": {"role": "assistant", "content": json.dumps(value)}}

    server.responses["/api/chat"] = reply
    result = generate_blueprint(references, BlueprintRequest(mode, "Record the inventory."),
                                "example:small", OllamaClient(port=server.port, timeout=10))
    assert len(calls) == 2
    assert all(isinstance(c["format"], dict) and "tools" not in c for c in calls)
    assert "PRIVATE DATA" not in json.dumps(calls)
    assert result["status"] == "draft"
    target = export_blueprint(result, tmp_path / mode)
    assert load_blueprint(target / "blueprint.json")["design"] == response
    report = (target / "report.html").read_text(encoding="utf-8")
    assert "Inventory" in report and "<svg" in report
    assert "script" not in report and "src=" not in report
    for svg in target.glob("*.svg"):
        ET.fromstring(svg.read_text(encoding="utf-8"))


@pytest.mark.parametrize("mode", ["engineering", "project", "software"])
def test_deterministic_checks_and_rendering(mode):
    result = document(mode)
    assert not [i for i in result["validation"]["issues"] if i["severity"] == "blocking"]
    assert drawings(result)
    if mode == "engineering":
        assert result["validation"]["calculations"][0]["value"] == 0.5
        assert set(drawings(result)) == {"top.svg", "front.svg", "side.svg"}
    if mode == "project":
        assert result["validation"]["schedule"][-1] == {"id": "P2", "start": 2, "end": 5}


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True, 10**400])
def test_nonfinite_invalid_dimensions_cannot_be_rendered(bad):
    value = design("engineering")
    value["parts"][0]["size_mm"][0] = bad
    with pytest.raises(ValueError):
        check_design("engineering", value, {"S1"})


def test_unknown_sources_requirements_cycles_and_units_block_release():
    value = design("engineering")
    value["parts"][0]["source_ids"] = ["INVENTED"]
    value["checks"][0]["requirement_id"] = "R2"
    value["steps"][0]["depends_on"] = ["A1"]
    value["calculations"][0]["inputs"][0]["unit"] = "mm"
    result = check_design("engineering", value, {"S1"})
    assert result["status"] == "needs_revision"
    assert len([i for i in result["issues"] if i["severity"] == "blocking"]) >= 5
    assert result["calculations"] == []


def test_dangling_software_edges_and_project_cycles():
    value = design("software")
    value["connections"][0]["target"] = "INVENTED"
    assert check_design("software", value, {"S1"})["status"] == "needs_revision"
    value = design("project")
    value["phases"][0]["depends_on"] = ["P2"]
    result = check_design("project", value, {"S1"})
    assert result["schedule"] == []
    assert result["status"] == "needs_revision"


def test_bounded_repair_then_review(references):
    class Client:
        calls = 0

        def generate(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return '{"title":"incomplete"}', False
            return json.dumps(design("project") if self.calls == 2 else {
                "findings": [{"severity": "blocking", "issue": "Budget unspecified.",
                              "recommendation": "Obtain a budget.", "source_ids": ["S1"]}],
                "missing_information": ["Budget"]}), False

    client = Client()
    result = generate_blueprint(references, BlueprintRequest("project", "Record inventory."),
                                "local", client)
    assert client.calls == 3 and len(result["attempts"]) == 2
    assert result["status"] == "needs_revision"


def test_missing_evidence_and_cancel_never_call_model(tmp_path):
    class Client:
        def generate(self, *_args, **_kwargs):
            pytest.fail("Model must not be called.")

    request = BlueprintRequest("engineering", "Design a workshop shelf.")
    library = KnowledgeLibrary(tmp_path / "empty.db")
    with pytest.raises(ValueError, match="No matching"):
        generate_blueprint(library, request, "local", Client())
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(GenerationCancelled):
        generate_blueprint(library, request, "local", Client(), cancel=cancelled)


def test_truncation_is_not_silently_accepted(references):
    class Client:
        def generate(self, *_args, **_kwargs):
            return json.dumps(design("project")), True

    with pytest.raises(LocalModelError, match="output limit"):
        generate_blueprint(references, BlueprintRequest("project", "Record inventory."),
                           "local", Client())


def test_export_escapes_model_html_and_refuses_existing_directory(tmp_path):
    value = document("software")
    value["design"]["components"][0]["name"] = '<script>alert("bad")</script>'
    value["design_sha256"] = digest(value["design"])
    assert '<script>' not in report_html(value)
    path = tmp_path / "existing"
    path.mkdir()
    sentinel = path / "user-data.txt"
    sentinel.write_text("keep")
    with pytest.raises(FileExistsError):
        export_blueprint(value, path)
    assert sentinel.read_text() == "keep"


def test_saved_design_checksum_and_strict_json(tmp_path):
    path = save_blueprint(document("project"), tmp_path / "design.json")
    value = json.loads(path.read_text())
    value["design"]["title"] = "Changed without updating checksum"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="checksum"):
        load_blueprint(path)
    path.write_text('{"version":1,"version":2}')
    with pytest.raises(ValueError, match="Duplicate"):
        load_blueprint(path)


def test_loaded_validation_is_recomputed_not_trusted(tmp_path):
    value = document("engineering")
    value["design"]["questions"] = ["Missing load rating"]
    value["design_sha256"] = digest(value["design"])
    value["validation"] = {"status": "approved"}
    report = report_html(copy.deepcopy(value))
    assert "Open questions" in report and "approved" not in report
    value["validation"] = {"status": "draft"}
    path = tmp_path / "untrusted.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    assert load_blueprint(path)["status"] == "needs_revision"


@pytest.mark.parametrize("mutation", [
    lambda v: v.pop("review"),
    lambda v: v.update(status="approved"),
    lambda v: v.update(review={"findings": []}),
    lambda v: v["sources"][0].update(checksum="unverified"),
    lambda v: v["sources"].append(v["sources"][0]),
])
def test_malformed_saved_documents_are_rejected(tmp_path, mutation):
    value = document("project")
    mutation(value)
    path = tmp_path / "malformed.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        load_blueprint(path)


def test_save_cannot_replace_unrelated_json_or_database(tmp_path):
    for filename, contents in (("library.json", '{"articles":[]}'), ("live.db", "SQLite format 3")):
        path = tmp_path / filename
        path.write_text(contents)
        with pytest.raises(ValueError):
            save_blueprint(document("engineering"), path)
        assert path.read_text() == contents


def test_materials_must_cover_real_parts():
    value = design("engineering")
    value["materials"][0]["part_ids"] = ["Missing"]
    result = check_design("engineering", value, {"S1"})
    assert len([i for i in result["issues"] if i["severity"] == "blocking"]) == 2


def test_invalid_critique_is_discarded_but_draft_can_be_saved(references, tmp_path):
    class Client:
        calls = 0

        def generate(self, *_args, **_kwargs):
            self.calls += 1
            return json.dumps(design("software") if self.calls == 1 else {"bad": True}), False

    result = generate_blueprint(references, BlueprintRequest("software", "Record inventory."),
                                "local", Client())
    assert result["review"] is None
    assert result["status"] == "needs_revision"
    assert result["review_error"]
    save_blueprint(result, tmp_path / "unreviewed.json")


def test_context_capacity_checked_before_sending_sources(server):
    server.responses["/api/show"] = {"capabilities": ["completion"],
                                     "details": {"format": "gguf"},
                                     "model_info": {"example.context_length": 4096}}
    with pytest.raises(LocalModelError, match="context capacity"):
        OllamaClient(port=server.port).generate(
            "example:small", [{"role": "user", "content": "Private design"}],
            schema={"type": "object"}, max_tokens=8192, cancel=threading.Event())
    assert not [request for request in server.requests if request[0] == "/api/chat"]


def test_refinement_uses_current_evidence_and_preserves_prior_design(references, server):
    calls = []

    def reply():
        request = server.requests[-1][1]
        calls.append(json.loads(request["messages"][1]["content"]))
        value = design("engineering") if len(calls) % 2 else {"findings": [], "missing_information": []}
        return {"done": True, "message": {"role": "assistant", "content": json.dumps(value)}}

    server.responses["/api/chat"] = reply
    request = BlueprintRequest("engineering", "Record the inventory.")
    client = OllamaClient(port=server.port, timeout=10)
    original = generate_blueprint(references, request, "example:small", client)
    snapshot = copy.deepcopy(original)
    # The article changes between revisions, so the old passage is no longer current.
    references.upsert(KnowledgeArticle("inventory", "Inventory", "Inventory uses a new shelf layout.", "projects"))
    updated = generate_blueprint(references, request, "example:small", client,
                                 previous=original, instructions="Reduce the shelf width to 600 mm.")
    assert original == snapshot
    assert updated["request"]["revision_of"] == digest(original)
    assert updated["request"]["revision_instructions"] == "Reduce the shelf width to 600 mm."
    assert updated["sources"][0]["checksum"] != original["sources"][0]["checksum"]
    context = calls[2]
    assert context["requested_changes"] == "Reduce the shelf width to 600 mm."
    assert context["previous_draft"]["citations_removed"] == ["S1"]
    assert context["previous_draft"]["design"]["parts"][0]["source_ids"] == []
    assert "PRIVATE DATA" not in json.dumps(calls)
    assert calls[3]["previous_draft"] == context["previous_draft"]


def test_refinement_remaps_unchanged_citations_and_rejects_empty_instructions(references):
    calls = []

    class Client:
        def generate(self, _model, messages, **kwargs):
            calls.append(json.loads(messages[1]["content"]))
            value = design("project") if len(calls) % 2 else {"findings": [], "missing_information": []}
            return json.dumps(value), False

    request = BlueprintRequest("project", "Record the inventory.")
    previous = generate_blueprint(references, request, "local", Client())
    generate_blueprint(references, request, "local", Client(), previous=previous,
                       instructions="Add a review step.")
    assert calls[2]["previous_draft"]["citations_removed"] == []
    assert calls[2]["previous_draft"]["design"]["requirements"][0]["source_ids"] == ["S1"]
    with pytest.raises(ValueError, match="5 to 4000"):
        generate_blueprint(references, request, "local", Client(), previous=previous, instructions=" ")
    assert len(calls) == 4


def test_constraints_and_resources_contribute_to_retrieval(tmp_path):
    from fieldforge.blueprints.engine import _sources

    library = KnowledgeLibrary(tmp_path / "refs.db")
    library.upsert(KnowledgeArticle("supply", "Timber", "Douglas fir timber stock information.", "materials"))
    library.upsert(KnowledgeArticle("power", "Battery", "Battery reserve sizing information.", "energy"))
    request = BlueprintRequest("engineering", "Develop a new prototype.",
                               constraints="Battery reserve", resources="Douglas fir timber")
    sources = _sources(library, request, "", lambda message: None)
    assert {s["slug"] for s in sources} == {"supply", "power"}


def test_existing_output_refused_before_model_or_database_access(tmp_path):
    from fieldforge.blueprints.__main__ import main

    path = tmp_path / "existing"
    path.mkdir()
    db = tmp_path / "not-created.db"
    with pytest.raises(SystemExit) as exc:
        main(["--database", str(db), "generate", "project", "Record the inventory.",
              "--model", "not-installed", "--output", str(path)])
    assert exc.value.code == 2
    assert not db.exists()
