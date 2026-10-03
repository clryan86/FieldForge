import copy
import json
import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from blueprint_fixtures import document, revision

from fieldforge.blueprints.__main__ import main
from fieldforge.blueprints.engine import digest
from fieldforge.blueprints.render import normalized_document, save_blueprint
from fieldforge.blueprints.review_files import (
    create_review,
    load_review,
    save_review,
    validate_review,
)
from fieldforge.blueprints.revision import export_revision, prepare_revision


def rehash(value):
    value["checksum"] = digest({key: item for key, item in value.items() if key != "checksum"})


@pytest.mark.parametrize("mode", ["engineering", "project", "software"])
def test_review_roundtrip_is_offline_portable_immutable_and_exports_resumable_file(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(socket, "socket", lambda *_a, **_kw: pytest.fail("Network used"))
    before = document(mode)
    candidate = revision(before)
    candidate["design"]["title"] = "Saved candidate"
    candidate["design_sha256"] = digest(candidate["design"])
    original = copy.deepcopy((before, candidate))
    value = create_review(before, candidate)
    path = save_review(value, tmp_path / "saved.ffreview.json")
    raw = path.read_bytes()
    reopened = load_review(path)
    assert reopened == value and path.read_bytes() == raw
    assert set(reopened) == {"format", "version", "created_at", "before", "candidate", "checksum"}
    assert str(tmp_path) not in raw.decode("utf-8")
    proposal = validate_review(reopened)
    assert proposal["before"] == before and proposal["candidate"] == normalized_document(candidate)
    assert proposal["candidate"]["sources"] == candidate["sources"]
    folder = export_revision(reopened["before"], reopened["candidate"], tmp_path / "report")
    assert load_review(folder / "review.ffreview.json")["before"] == before
    assert (folder / "comparison" / "before.json").is_file()
    assert (before, candidate) == original


@pytest.mark.parametrize("change,match", [
    ("tamper", "checksum"), ("lineage", "original draft"), ("limits", "acceptance limits"),
    ("version", "Unsupported"), ("extra", "Unsupported"), ("timestamp", "timestamp"),
    ("instructions", "instructions"), ("nested", "Malformed"),
])
def test_review_rejects_corruption_and_malformed_metadata_before_use(tmp_path, change, match):
    before = document("engineering")
    value = create_review(before, revision(before))
    if change == "tamper":
        value["candidate"]["design"]["title"] = "Tampered title"
    elif change == "lineage":
        value["candidate"]["request"]["revision_of"] = "0" * 64
    elif change == "limits":
        value["candidate"]["request"]["acceptance_rules"] = [{
            "id": "L1", "label": "Changed limit", "metric": "part.size_x", "target": "P1",
            "unit": "mm", "operator": "<=", "value": 500}]
    elif change == "version":
        value["version"] = True
    elif change == "extra":
        value["project_path"] = "private-location"
    elif change == "timestamp":
        value["created_at"] = "2026-10-01T01:00:00"  # No timezone.
    elif change == "instructions":
        value["candidate"]["request"]["revision_instructions"] = ""
    else:
        value["before"]["request"] = []
    if change != "tamper":
        rehash(value)
    path = tmp_path / "invalid.ffreview.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        load_review(path)


def test_stored_checks_are_recomputed_without_rewriting_historical_lineage(tmp_path):
    from fieldforge.blueprints.review_files import review_from_files

    before = document("project")
    before["validation"] = {"status": "draft", "old_checker_field": "historical results"}
    candidate = revision(normalized_document(before))
    candidate["request"]["revision_of"] = digest(before)
    candidate["design"]["questions"] = ["A missing site measurement remains unresolved."]
    candidate["design_sha256"] = digest(candidate["design"])
    candidate["validation"] = {"status": "draft"}
    value = {"format": "fieldforge-revision-review", "version": 1, "created_at": "2026-10-01T00:00:00+00:00",
             "before": before, "candidate": candidate}
    rehash(value)
    original = copy.deepcopy(value)
    path = save_review(value, tmp_path / "historical.ffreview.json")
    proposal = validate_review(load_review(path))
    assert proposal["before"] == before and proposal["before"]["validation"]["old_checker_field"]
    assert proposal["base_snapshot_sha256"] == digest(normalized_document(before))
    assert proposal["candidate"]["status"] == "needs_revision"
    assert prepare_revision(proposal["before"], proposal["candidate"]) == proposal
    assert load_review(path) == original and value == original
    saved_again = create_review(proposal["before"], proposal["candidate"])
    assert saved_again["before"] == before
    assert saved_again["candidate"]["request"]["revision_of"] == digest(before)
    first, second = tmp_path / "old-before.json", tmp_path / "old-candidate.json"
    first.write_text(json.dumps(before), encoding="utf-8")
    second.write_text(json.dumps(candidate), encoding="utf-8")
    assert review_from_files(first, second)["before"] == before


@pytest.mark.parametrize("raw", [b'{"format":1,"format":2}', b'{"value":NaN}', b'\xff', b'[' * 2000])
def test_review_strict_json_rejects_duplicate_nonfinite_encoding_and_excessive_nesting(tmp_path, raw):
    path = tmp_path / "bad.ffreview.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        load_review(path)


def test_review_size_limits_and_destination_protection(tmp_path, monkeypatch):
    import fieldforge.blueprints.review_files as files

    value = create_review(document("software"), revision(document("software")))
    target = tmp_path / "existing.ffreview.json"
    target.write_bytes(b"unrelated user file")
    with pytest.raises(FileExistsError):
        save_review(value, target)
    assert target.read_bytes() == b"unrelated user file"
    with pytest.raises(ValueError, match="extension"):
        save_review(value, tmp_path / "wrong.json")
    monkeypatch.setattr(files, "MAX_BYTES", 10)
    with pytest.raises(ValueError, match="6 MB"):
        load_review(target)
    with pytest.raises(ValueError, match="6 MB"):
        save_review(value, tmp_path / "large.ffreview.json")
    monkeypatch.setattr(files, "BLUEPRINT_BYTES", 10)
    with pytest.raises(ValueError, match="2 MB"):
        validate_review(value)
    assert not (tmp_path / "large.ffreview.json").exists()


def test_failed_atomic_review_save_leaves_no_partial_file_and_can_be_retried(tmp_path, monkeypatch):
    value = create_review(document("project"), revision(document("project")))
    target = tmp_path / "atomic.ffreview.json"

    def fail(*_a, **_kw):
        raise OSError("Simulated write failure")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail)
        with pytest.raises(OSError, match="Simulated"):
            save_review(value, target)
    assert not target.exists() and not list(tmp_path.glob(".blueprint-*"))
    save_review(value, target)
    assert load_review(target) == value


def test_cooperating_review_writers_never_overwrite_the_first_complete_file(tmp_path):
    value = create_review(document("project"), revision(document("project")))
    target = tmp_path / "concurrent.ffreview.json"

    def write():
        try:
            save_review(value, target)
            return "saved"
        except (FileExistsError, ValueError):
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: write(), range(2)))
    assert sorted(results) == ["blocked", "saved"]
    assert load_review(target) == value


def test_review_cli_needs_no_database_or_model_and_preserves_all_input_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(socket, "socket", lambda *_a, **_kw: pytest.fail("Network used"))
    before = document("engineering")
    candidate = revision(before)
    candidate["design"]["questions"] = ["Missing material data."]
    candidate["design_sha256"] = digest(candidate["design"])
    first = save_blueprint(before, tmp_path / "before.json")
    second = save_blueprint(candidate, tmp_path / "candidate.json")
    original = (first.read_bytes(), second.read_bytes())
    target = tmp_path / "review.ffreview.json"
    db = tmp_path / "must-not-exist.db"
    assert main(["--database", str(db), "review-save", str(first), str(second), str(target)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "needs_revision" and result["applied"] is False
    raw = target.read_bytes()
    assert main(["review-check", str(target)]) == 0
    assert json.loads(capsys.readouterr().out)["checksum"] == result["checksum"]
    assert main(["review-export", str(target), str(tmp_path / "export")]) == 0
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        main(["review-save", str(first), str(second), str(target)])
    assert exc.value.code == 2
    assert target.read_bytes() == raw and (first.read_bytes(), second.read_bytes()) == original
    assert not db.exists()
