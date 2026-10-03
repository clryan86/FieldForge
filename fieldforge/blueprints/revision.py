"""Isolated AI revision proposals and offline review exports."""

from __future__ import annotations

import copy
from pathlib import Path

from fieldforge.blueprints.comparison import compare_results
from fieldforge.blueprints.comparison_report import export_comparison
from fieldforge.blueprints.engine import digest
from fieldforge.blueprints.render import export_blueprint, normalized_document, readable


def prepare_revision(before, candidate):
    """Recheck both snapshots; a desktop refinement must retain its applied limits."""
    recorded_before = copy.deepcopy(before)
    before = normalized_document(recorded_before)
    candidate = normalized_document(copy.deepcopy(candidate))
    if before["request"]["mode"] != candidate["request"]["mode"]:
        raise ValueError("The candidate uses a different blueprint maker.")
    lineage = candidate["request"].get("revision_of")
    if lineage not in {digest(recorded_before), digest(before)}:
        raise ValueError("The candidate does not reference the captured original draft.")
    if before["request"].get("acceptance_rules", []) != candidate["request"].get("acceptance_rules", []):
        raise ValueError("The candidate changed the applied acceptance limits.")
    # Preserve the exact snapshot named by the candidate. Future checker changes
    # may alter derived validation; recomputation must not rewrite that lineage.
    snapshot = recorded_before if lineage == digest(recorded_before) else before
    return {"before": snapshot, "candidate": candidate, "base_snapshot_sha256": digest(before),
            "comparison": compare_results(before, candidate)}


def candidate_text(value):
    """Complete accessible text equivalent, including request, critique and evidence."""
    value = normalized_document(value)
    return "\n\n".join(("PROPOSED AI REVISION — not applied or certified",
                        "STATUS: " + value["status"], "MODEL: " + value["model"],
                        "REQUEST\n" + readable(value["request"]),
                        "DESIGN\n" + readable(value["design"]),
                        "DETERMINISTIC CHECKS\n" + readable(value["validation"]),
                        "MODEL CRITIQUE (not independent review)\n" + readable(value["review"]),
                        value["review_error"], "SOURCE EVIDENCE\n" + readable(value["sources"])))


def export_revision(before, candidate, destination):
    """Export a candidate and fixed-baseline comparison without applying any change."""
    proposal = prepare_revision(before, candidate)
    from fieldforge.blueprints.review_files import create_review, save_review
    review = create_review(proposal["before"], proposal["candidate"])
    destination = Path(destination)
    export_blueprint(proposal["candidate"], destination)
    export_comparison(proposal["before"], proposal["candidate"], destination / "comparison")
    save_review(review, destination / "review.ffreview.json")
    (destination / "REVISION_REVIEW.txt").write_text(
        "Unapplied AI revision proposal. Exporting does not accept it or change project history.\n"
        "Open report.html for the candidate and comparison/report.html for recomputed outcomes.\n"
        "review.ffreview.json resumes the unapplied review in the matching desktop maker.\n"
        "The comparison folder preserves complete before/after snapshots. Review the evidence,\n"
        "blocking issues and original-limit regressions before adopting any change.\n"
        "A model critique is not independent review or certification.\n", encoding="utf-8")
    return destination
