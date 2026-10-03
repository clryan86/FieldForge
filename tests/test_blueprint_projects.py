import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from blueprint_fixtures import document

from fieldforge.blueprints.__main__ import main
from fieldforge.blueprints.engine import digest
from fieldforge.blueprints.projects import (
    RevisionConflict,
    append_revision,
    checkout,
    compare_designs,
    create_project,
    head,
    load_project,
    restore_revision,
)
from fieldforge.blueprints.render import save_blueprint


def changed(mode="engineering", title="Revised design"):
    value = document(mode)
    value["design"]["title"] = title
    value["design_sha256"] = digest(value["design"])
    return value


@pytest.mark.parametrize("mode", ["engineering", "project", "software"])
def test_history_survives_reopen_and_restores_without_deleting_versions(tmp_path, mode):
    path = tmp_path / "design.ffproject.json"
    initial = document(mode)
    project = create_project(path, "Local project", initial)
    old_head = head(project)
    project = append_revision(path, changed(mode), expected_head=old_head,
                              kind="refined", note="Revise title")
    assert checkout(load_project(path))["design"]["title"] == "Revised design"
    assert project["revisions"][0]["checksum"] == old_head
    # An old in-memory view cannot replace the newer project.
    before = path.read_bytes()
    with pytest.raises(RevisionConflict, match="changed on disk"):
        append_revision(path, initial, expected_head=old_head)
    assert path.read_bytes() == before
    project = restore_revision(path, 1, expected_head=head(project))
    assert len(project["revisions"]) == 3
    assert project["revisions"][-1]["kind"] == "restored"
    assert checkout(project) == initial
    assert checkout(project, 2)["design"]["title"] == "Revised design"
    # Returning a revision never lets callers mutate stored history accidentally.
    extracted = checkout(project)
    extracted["design"]["title"] = "Mutated"
    assert checkout(project)["design"]["title"] == "Example design"


def test_create_rejects_existing_files_and_wrong_extension(tmp_path):
    path = tmp_path / "live.ffproject.json"
    path.write_bytes(b"SQLite format 3\0existing user data")
    with pytest.raises(FileExistsError):
        create_project(path, "Project", document("project"))
    assert path.read_bytes().startswith(b"SQLite format 3")
    with pytest.raises(ValueError, match="extension"):
        create_project(tmp_path / "library.db", "Project", document("project"))


def test_older_blueprint_without_revision_metadata_can_start_a_project(tmp_path):
    value = document("software")
    del value["request"]["revision_instructions"]
    del value["request"]["revision_of"]
    path = tmp_path / "legacy.ffproject.json"
    project = create_project(path, "Older saved design", value)
    assert checkout(load_project(path)) == value
    assert head(project) == head(load_project(path))


def test_oversized_revision_count_is_rejected_before_reading_records(tmp_path):
    path = tmp_path / "oversized.ffproject.json"
    project = create_project(path, "Project", document("project"))
    project["revisions"] *= 101
    path.write_text(json.dumps(project), encoding="utf-8")
    with pytest.raises(ValueError, match="100 revisions"):
        load_project(path)


def test_checksum_chain_and_mode_validation(tmp_path):
    path = tmp_path / "project.ffproject.json"
    project = create_project(path, "Project", document("project"))
    with pytest.raises(ValueError, match="mix"):
        append_revision(path, document("software"), expected_head=head(project))
    assert len(load_project(path)["revisions"]) == 1
    project["revisions"][0]["note"] = "Tampered history"
    path.write_text(json.dumps(project), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        load_project(path)
    path.write_text('{"version":1,"version":2}', encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        load_project(path)


def test_two_writers_cannot_lose_each_others_revisions(tmp_path):
    path = tmp_path / "project.ffproject.json"
    project = create_project(path, "Project", document("engineering"))
    expected = head(project)
    barrier = threading.Barrier(2)

    def write(index):
        barrier.wait(timeout=3)
        try:
            append_revision(path, changed(title=f"Writer {index}"), expected_head=expected)
            return "saved"
        except RevisionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, (1, 2)))
    assert sorted(results) == ["conflict", "saved"]
    assert len(load_project(path)["revisions"]) == 2


def test_atomic_replace_failure_preserves_complete_project(tmp_path, monkeypatch):
    path = tmp_path / "project.ffproject.json"
    project = create_project(path, "Project", document("engineering"))
    before = path.read_bytes()

    def fail(*_args, **_kwargs):
        raise OSError("Simulated disk failure")

    # Patch the operation used by the writer: Python 3.10's pathlib caches
    # os.replace in an accessor, so patching os.replace misses this failure.
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="disk failure"):
        append_revision(path, changed(), expected_head=head(project))
    assert path.read_bytes() == before
    assert len(load_project(path)["revisions"]) == 1
    assert not list(tmp_path.glob(".blueprint-*"))


def test_comparison_tracks_part_ids_and_bounds_large_diffs():
    before = document("engineering")
    second = copy.deepcopy(before["design"]["parts"][0])
    second["id"] = "P2"
    before["design"]["parts"].append(second)
    after = copy.deepcopy(before)
    after["design"]["parts"].reverse()
    after["design"]["parts"][1]["size_mm"][0] = 600
    rows = compare_designs(before, after)["changes"]
    assert {r["path"] for r in rows} == {"/design/parts/P1/size_mm", "/design/parts/order"}
    limited = compare_designs(before, after, limit=1)
    assert len(limited["changes"]) == 1 and limited["truncated"]


def test_project_cli_lifecycle_never_opens_library_database(tmp_path, capsys):
    db = tmp_path / "must-not-exist.db"
    source = save_blueprint(document("project"), tmp_path / "initial.json")
    updated = save_blueprint(changed("project"), tmp_path / "updated.json")
    project_path = tmp_path / "cli.ffproject.json"
    prefix = ["--database", str(db)]
    assert main(prefix + ["project-init", str(source), str(project_path)]) == 0
    initial = json.loads(capsys.readouterr().out)
    assert main(prefix + ["project-add", str(project_path), str(updated), "--expect", initial["head"]]) == 0
    revised = json.loads(capsys.readouterr().out)
    assert len(revised["revisions"]) == 2
    assert main(prefix + ["compare", str(source), str(updated)]) == 0
    assert json.loads(capsys.readouterr().out)["changes"][0]["path"] == "/design/title"
    assert main(prefix + ["project-restore", str(project_path), "1", "--expect", revised["head"]]) == 0
    assert len(json.loads(capsys.readouterr().out)["revisions"]) == 3
    assert main(prefix + ["project-history", str(project_path)]) == 0
    assert len(json.loads(capsys.readouterr().out)["revisions"]) == 3
    output = tmp_path / "report"
    assert main(prefix + ["project-export", str(project_path), str(output), "--revision", "2"]) == 0
    capsys.readouterr()
    assert (output / "report.html").exists()
    assert json.loads((output / "blueprint.json").read_text())["design"]["title"] == "Revised design"
    assert not db.exists()
