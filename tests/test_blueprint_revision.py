import copy
import json
import socket

import pytest
from blueprint_fixtures import document, revision
from test_blueprint_clearance import limit
from test_blueprint_geometry import pair

from fieldforge.blueprints.engine import digest
from fieldforge.blueprints.render import load_blueprint, normalized_document
from fieldforge.blueprints.revision import candidate_text, export_revision, prepare_revision


@pytest.mark.parametrize("mode", ["engineering", "project", "software"])
def test_proposal_recomputes_untrusted_results_and_isolates_both_snapshots(mode):
    before = document(mode)
    candidate = revision(before)
    candidate["design"]["questions"] = ["Missing input still needs an answer."]
    candidate["design_sha256"] = digest(candidate["design"])
    candidate["validation"] = {"status": "draft"}
    original = copy.deepcopy((before, candidate))
    proposal = prepare_revision(before, candidate)
    assert (before, candidate) == original
    assert proposal["candidate"]["status"] == "needs_revision"
    assert proposal["comparison"]["before"]["snapshot_sha256"] == digest(normalized_document(before))
    assert proposal["comparison"]["after"]["snapshot_sha256"] == digest(proposal["candidate"])
    text = candidate_text(proposal["candidate"])
    assert "Missing input" in text and "Keep an inventory." in text and "not independent review" in text
    proposal["candidate"]["design"]["title"] = "Changed isolated candidate"
    proposal["before"]["design"]["title"] = "Changed isolated baseline"
    assert (before, candidate) == original


def test_regressions_are_visible_even_with_a_positive_model_critique():
    before = pair((15, 0, 0))
    before["request"]["acceptance_rules"] = [limit()]
    candidate = revision(before)
    candidate["design"]["parts"][1]["position_mm"] = [12, 0, 0]
    candidate["design_sha256"] = digest(candidate["design"])
    proposal = prepare_revision(before, candidate)
    assert proposal["comparison"]["acceptance"]["outcomes"] == {"regressed": 1}
    assert proposal["candidate"]["status"] == "needs_revision"
    assert proposal["candidate"]["review"]["findings"] == []


@pytest.mark.parametrize("change,match", [("lineage", "original draft"), ("rules", "acceptance limits"),
                                         ("mode", "different blueprint"), ("checksum", "checksum")])
def test_wrong_lineage_limits_mode_or_corrupt_candidate_cannot_be_proposed(change, match):
    before = document("engineering")
    candidate = revision(before)
    if change == "lineage":
        candidate["request"]["revision_of"] = "0" * 64
    elif change == "rules":
        candidate["request"]["acceptance_rules"] = [limit()]
    elif change == "mode":
        candidate = revision(document("software"))
    else:
        candidate["design"]["title"] = "Unhashed change"
    with pytest.raises(ValueError, match=match):
        prepare_revision(before, candidate)


@pytest.mark.parametrize("mode", ["engineering", "project", "software"])
def test_review_export_is_offline_reopenable_and_refuses_to_overwrite(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(socket, "socket", lambda *_a, **_kw: pytest.fail("Network used"))
    before = document(mode)
    candidate = revision(before)
    candidate["design"]["title"] = "Proposed <script>alert(1)</script> title"
    candidate["design_sha256"] = digest(candidate["design"])
    originals = copy.deepcopy((before, candidate))
    target = export_revision(before, candidate, tmp_path / "candidate")
    assert load_blueprint(target / "blueprint.json") == normalized_document(candidate)
    comparison = json.loads((target / "comparison" / "comparison.json").read_text(encoding="utf-8"))
    assert comparison["before"]["snapshot_sha256"] == digest(normalized_document(before))
    assert "&lt;script&gt;" in (target / "report.html").read_text(encoding="utf-8")
    assert "Unapplied" in (target / "REVISION_REVIEW.txt").read_text(encoding="utf-8")
    snapshot = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    with pytest.raises(FileExistsError):
        export_revision(before, candidate, target)
    assert snapshot == {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    assert (before, candidate) == originals


def test_invalid_proposal_creates_no_partial_export(tmp_path):
    value = document("project")
    with pytest.raises(ValueError, match="original draft"):
        export_revision(value, value, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()
