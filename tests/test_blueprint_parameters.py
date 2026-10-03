import copy
import json
import socket
from decimal import getcontext

import pytest
from blueprint_fixtures import document
from test_blueprint_clearance import limit
from test_blueprint_geometry import pair

from fieldforge.blueprints.__main__ import main
from fieldforge.blueprints.engine import digest
from fieldforge.blueprints.parameters import editable_parts, parse_length, prepare_part_edit
from fieldforge.blueprints.projects import (
    append_revision,
    checkout,
    create_project,
    head,
    load_project,
)
from fieldforge.blueprints.render import load_blueprint, save_blueprint


@pytest.mark.parametrize("text,expected", [
    ("250", 250), (" 250 MM ", 250), ("25cm", 250), (".25 m", 250), ("1e-3m", 1),
    ("12 in", 304.8), ("1 ft", 304.8), (".5IN", 12.7), ("+2.5e1 mm", 25),
    ("1000 m", 1_000_000), ("0", 0), ("-0", 0), ("5e-324 mm", 5e-324), ("5e-327m", 5e-324),
])
def test_lengths_convert_exactly_to_supported_millimeter_numbers(text, expected):
    precision = getcontext().prec
    assert parse_length(text) == expected and getcontext().prec == precision


@pytest.mark.parametrize("text", [
    "", "NaN", "inf", "-1", "1001 m", "1000001 mm", "3 yd", "1/2 in", '1"',
    "1,000", "1+2", "1 m + 2 cm", "__import__('os')", "1e99999", "1e-99999", "1e-999999999",
    "1e-325", "0.1234567890123456789", "1.23456789012345678 in", "9" * 81, 5, None,
])
def test_invalid_or_unrepresentable_lengths_are_rejected_without_rounding(text):
    with pytest.raises(ValueError):
        parse_length(text)


@pytest.mark.parametrize("text", ["0", "-0.0 m", "0e-200"])
def test_sizes_must_be_positive_while_positions_may_be_zero(text):
    assert parse_length(text) == 0
    with pytest.raises(ValueError, match="positive"):
        parse_length(text, positive=True)


def test_preview_changes_only_selected_measurements_preserves_rules_and_invalidates_critique():
    source = pair((15, 0, 0))
    source["request"]["acceptance_rules"] = [limit()]
    original = copy.deepcopy(source)
    result = prepare_part_edit(source, "P2", size=["1 cm", "1 cm", "12 mm"], position=["12mm", "0", "0"])
    value = result["blueprint"]
    assert source == original
    assert value["request"] == source["request"] and value["sources"] == source["sources"]
    assert value["design"]["parts"][1]["size_mm"] == [10, 10, 12]
    assert value["design"]["parts"][1]["position_mm"] == [12, 0, 0]
    assert value["design"]["parts"][0] == source["design"]["parts"][0]
    for key in ("materials", "calculations", "steps", "requirements", "questions"):
        assert value["design"][key] == source["design"][key]
    assert value["review"] is None and "new review" in value["review_error"]
    assert value["status"] == "needs_revision"
    assert value["design_sha256"] == digest(value["design"])
    assert result["comparison"]["acceptance"]["outcomes"] == {"regressed": 1}
    assert result["base_snapshot_sha256"] == result["comparison"]["before"]["snapshot_sha256"]
    assert "not rewritten" in result["notice"]


def test_improved_checks_do_not_reinstate_a_model_review_or_certify_draft():
    source = pair((12, 0, 0))
    source["request"]["acceptance_rules"] = [limit()]
    result = prepare_part_edit(source, "P2", position=["1.5cm", "0", "0"])
    assert result["comparison"]["acceptance"]["outcomes"] == {"now_passes": 1}
    assert result["blueprint"]["status"] == "needs_revision" and result["blueprint"]["review"] is None
    assert result["blueprint"]["design"]["parts"][1]["size_mm"] == [10, 10, 10]


def test_bad_id_empty_ambiguous_and_nonengineering_designs_fail_closed():
    source = pair()
    with pytest.raises(ValueError, match="Unknown part"):
        prepare_part_edit(source, "MISSING", size=["1", "2", "3"])
    for mode in ("software", "project"):
        with pytest.raises(ValueError, match="engineering"):
            editable_parts(document(mode))
    source["design"]["parts"][0]["id"] = "P2"
    source["design_sha256"] = digest(source["design"])
    with pytest.raises(ValueError, match="unique"):
        prepare_part_edit(source, "P2", size=["1", "2", "3"])
    source["design"]["parts"] = []
    source["design_sha256"] = digest(source["design"])
    with pytest.raises(ValueError, match="at least one"):
        editable_parts(source)


def test_incomplete_input_no_change_and_bad_checksum_do_not_create_candidates():
    source = pair()
    for kwargs in ({}, {"size": []}, {"size": "1 2 3"}, {"position": ["1", "2"]}):
        with pytest.raises(ValueError):
            prepare_part_edit(source, "P1", **kwargs)
    with pytest.raises(ValueError, match="unchanged"):
        prepare_part_edit(source, "P1", size=["1cm", "1cm", "1cm"])
    with pytest.raises(ValueError, match="size_mm Y"):
        prepare_part_edit(source, "P1", size=["1", "0", "1"])
    source["design"]["parts"][0]["size_mm"][0] = 100
    with pytest.raises(ValueError, match="checksum"):
        prepare_part_edit(source, "P1", position=["1", "0", "0"])


def test_editable_parts_and_candidates_are_isolated_from_original():
    source = pair()
    original = copy.deepcopy(source)
    editable_parts(source)[0]["size_mm"][0] = 1
    result = prepare_part_edit(source, "P1", size=["2", "3", "4"])
    result["blueprint"]["request"]["acceptance_rules"].append(limit())
    assert source == original


def test_offline_cli_exports_drawings_and_fixed_baseline_comparison_and_never_overwrites(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(socket, "socket", lambda *_a, **_kw: pytest.fail("Network used"))
    value = pair((15, 0, 0))
    value["request"]["acceptance_rules"] = [limit()]
    source = save_blueprint(value, tmp_path / "source.json")
    original = source.read_bytes()
    db, target = tmp_path / "must-not-exist.db", tmp_path / "edited"
    args = ["--database", str(db), "edit-part", str(source), "P2", "--position", "12mm", "0", "0", "--output", str(target)]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "needs_revision" and result["acceptance_outcomes"] == {"regressed": 1}
    assert (target / "isometric.svg").is_file() and (target / "comparison" / "report.html").is_file()
    exported = load_blueprint(target / "blueprint.json")
    compared = json.loads((target / "comparison" / "comparison.json").read_text(encoding="utf-8"))
    assert exported["design"]["parts"][1]["position_mm"] == [12, 0, 0]
    assert compared["acceptance"]["outcomes"] == {"regressed": 1}
    snapshot = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
    assert snapshot == {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    assert not db.exists() and source.read_bytes() == original
    invalid = tmp_path / "invalid"
    with pytest.raises(SystemExit):
        main(["edit-part", str(source), "P2", "--size", "0", "1", "2", "--output", str(invalid)])
    assert not invalid.exists()


def test_history_can_store_and_restore_parameter_revision_without_altering_original_record(tmp_path):
    source = pair((15, 0, 0))
    source["request"]["acceptance_rules"] = [limit()]
    project = create_project(tmp_path / "design.ffproject.json", "Part edits", source)
    first = copy.deepcopy(project["revisions"][0])
    edited = prepare_part_edit(checkout(project), "P2", position=["12", "0", "0"])["blueprint"]
    append_revision(tmp_path / "design.ffproject.json", edited, expected_head=head(project), note="Move P2")
    reopened = load_project(tmp_path / "design.ffproject.json")
    assert reopened["revisions"][0] == first
    assert checkout(reopened)["design"]["parts"][1]["position_mm"][0] == 12
    assert checkout(reopened, 1)["design"]["parts"][1]["position_mm"][0] == 15
