import copy
import json
import socket
from decimal import getcontext

import pytest
from blueprint_fixtures import document
from test_blueprint_clearance import limit
from test_blueprint_geometry import pair

from fieldforge.blueprints.__main__ import main
from fieldforge.blueprints.comparison import compare_results, comparison_text
from fieldforge.blueprints.comparison_report import export_comparison
from fieldforge.blueprints.engine import digest
from fieldforge.blueprints.projects import append_revision, create_project, head, load_project
from fieldforge.blueprints.render import load_blueprint, save_blueprint


def sealed(value):
    value["design_sha256"] = digest(value["design"])
    return value


def test_fixed_baseline_exposes_regression_even_when_limit_is_weakened():
    before, after = pair((15, 0, 0)), pair((12, 0, 0))
    before["request"]["acceptance_rules"] = [limit(value=5)]
    after["request"]["acceptance_rules"] = [limit(value=2)]
    # Saved calculations/status are untrusted, even if the design checksum is intact.
    after["validation"] = {"acceptance": [{"status": "passed"}]}
    snapshots = copy.deepcopy((before, after))
    result = compare_results(before, after)
    assert (before, after) == snapshots
    acceptance = result["acceptance"]
    assert acceptance["outcomes"] == {"regressed": 1}
    row = acceptance["fixed_baseline"][0]
    assert row["before"]["actual"] == "5" and row["after"]["actual"] == "2"
    assert row["after"]["status"] == "failed" and row["rule"]["value"] == 5
    assert acceptance["current_results"][0]["status"] == "passed"
    assert acceptance["rule_changes"][0]["change"] == "criteria_changed"
    assert result["geometry"]["pairs"][0]["clearance_change"] == "decreased"
    text = comparison_text(result)
    assert "regressed" in text and "criteria changed" in text and "current rules" in text


@pytest.mark.parametrize("change", ["removed", "renamed", "replaced"])
def test_removing_or_replacing_a_rule_does_not_hide_a_failed_baseline(change):
    before, after = pair((12, 0, 0)), pair((12, 0, 0))
    before["request"]["acceptance_rules"] = [limit()]
    after["request"]["acceptance_rules"] = [] if change == "removed" else [limit(id="NEW", value=1)]
    if change == "replaced":
        after["request"]["acceptance_rules"] = [limit("relation", "separated", "=")]
    result = compare_results(before, after)
    assert result["acceptance"]["outcomes"] == {"still_failed": 1}
    assert "now_passes" not in result["acceptance"]["outcomes"]


def test_new_pass_and_cosmetic_rule_changes_are_separate():
    before, after = pair((12, 0, 0)), pair((15, 0, 0))
    before["request"]["acceptance_rules"] = [limit()]
    after["request"]["acceptance_rules"] = [limit(label="Reworded", target="P2/P1")]
    result = compare_results(before, after)
    assert result["acceptance"]["outcomes"] == {"now_passes": 1}
    assert result["acceptance"]["rule_changes"][0]["change"] == "description_changed"
    after["request"]["acceptance_rules"].append(limit(id="ADDED"))
    assert compare_results(before, after)["acceptance"]["rule_changes"][0]["change"] == "added"


def test_missing_target_is_unresolved_and_pairs_match_ids_not_array_positions():
    before = pair((15, 0, 0))
    before["request"]["acceptance_rules"] = [limit()]
    after = copy.deepcopy(before)
    after["design"]["parts"].reverse()
    result = compare_results(before, sealed(after))
    assert result["geometry"]["pairs"] == [] and result["geometry"]["unchanged_pairs"] == 1
    assert result["geometry"]["parts"]["changes"] == []
    after["design"]["parts"].pop(0)
    result = compare_results(before, sealed(after))
    assert result["acceptance"]["fixed_baseline"][0]["after"]["status"] == "unresolved"
    assert result["acceptance"]["outcomes"] == {"regressed": 1}
    assert result["geometry"]["pairs"][0]["change"] == "removed"
    assert result["geometry"]["parts"]["changes"][0]["id"] == "P2"
    reverse = compare_results(sealed(after), before)
    assert reverse["geometry"]["pairs"][0]["change"] == "added"
    assert reverse["geometry"]["pairs"][0]["clearance_change"] == "not_comparable"


@pytest.mark.parametrize("broken", ["zero", "duplicate", "empty"])
def test_unresolved_geometry_never_looks_like_all_overlaps_were_fixed(broken):
    before, after = pair(), pair()
    if broken == "zero":
        after["design"]["parts"][0]["size_mm"][0] = 0
    elif broken == "duplicate":
        after["design"]["parts"][0]["id"] = "P2"
    else:
        after["design"]["parts"] = []
    result = compare_results(before, sealed(after))
    assert result["geometry"]["status"] == "unresolved"
    assert result["geometry"]["pairs"] == []
    assert result["geometry"]["span_after_mm"] is None
    assert "Unresolved geometry is not a clean result" in comparison_text(result)
    if broken == "duplicate":
        assert result["geometry"]["parts"]["status"] == "unresolved"


def test_rounded_clearances_and_tiny_spans_keep_exact_direction():
    before, after = pair((11, 10, 0)), pair((11, 10.000000001, 0))
    before["request"]["acceptance_rules"] = [limit(value=1, operator="<=")]
    precision = getcontext().prec
    result = compare_results(before, after)
    row = result["geometry"]["pairs"][0]
    assert row["before"]["clearance_mm"] == row["after"]["clearance_mm"] == "1"
    assert row["clearance_change"] == "increased"
    assert result["acceptance"]["outcomes"] == {"regressed": 1}
    assert "approximately 1 mm" in comparison_text(result)
    tiny = document("engineering")
    tiny["design"]["parts"][0].update(size_mm=[5e-324, 1, 1], position_mm=[1e6, 0, 0])
    result = compare_results(sealed(tiny), sealed(tiny))
    assert result["geometry"]["span_after_mm"][0] == "5E-324"
    assert getcontext().prec == precision


def test_contact_changes_are_visible_when_clearance_stays_zero():
    result = compare_results(pair(), pair((10, 0, 0)))
    row = result["geometry"]["pairs"][0]
    assert row["clearance_change"] == "unchanged"
    assert row["before"]["relation"] == "overlap" and row["after"]["relation"] == "face_contact"
    assert result["geometry"]["before"]["overlap_pairs"] == 1
    assert result["geometry"]["after"]["face_contact_pairs"] == 1


def test_complete_pair_results_are_kept_when_readable_view_is_bounded():
    before = document("engineering")
    template = before["design"]["parts"][0]
    before["design"]["parts"] = [{**template, "id": f"P{i}", "size_mm": [1, 1, 1],
                                  "position_mm": [i * 2, 0, 0]} for i in range(60)]
    after = copy.deepcopy(before)
    for i, part in enumerate(after["design"]["parts"]):
        part["position_mm"] = [i * 3, 0, 0]
    result = compare_results(sealed(before), sealed(after))
    assert len(result["geometry"]["pairs"]) == 1770
    text = comparison_text(result, pair_limit=1)
    assert "1769 additional pair changes omitted" in text
    assert len(result["geometry"]["pairs"]) == 1770
    with pytest.raises(ValueError, match="display limit"):
        comparison_text(result, pair_limit=0)


@pytest.mark.parametrize("mode,metric,target,unit,value", [
    ("project", "project.duration", "", "day", 5),
    ("software", "component.trust_zone", "DB", "text", "device"),
])
def test_non_engineering_makers_compare_fixed_checks_without_geometry(mode, metric, target, unit, value):
    before = document(mode)
    before["request"]["acceptance_rules"] = [{"id": "L1", "label": "Preserve limit", "metric": metric,
        "target": target, "unit": unit, "value": value, "operator": "="}]
    after = copy.deepcopy(before)
    if mode == "project":
        after["design"]["phases"][0]["duration_days"] = 4
    else:
        after["design"]["components"][1]["trust_zone"] = "remote"
    result = compare_results(before, sealed(after))
    assert "geometry" not in result
    assert result["acceptance"]["outcomes"] == {"regressed": 1}
    assert "regressed" in comparison_text(result)


def test_invalid_mismatched_and_legacy_inputs():
    before = document("engineering")
    with pytest.raises(ValueError, match="same maker"):
        compare_results(before, document("software"))
    after = copy.deepcopy(before)
    after["design"]["parts"][0]["size_mm"][0] = 100
    with pytest.raises(ValueError, match="checksum"):
        compare_results(before, after)
    del before["request"]["acceptance_rules"]
    result = compare_results(before, before)
    assert "No baseline limits" in comparison_text(result)
    assert result["acceptance"]["baseline_count"] == 0
    assert "acceptance_rules" not in before["request"]


def test_portable_export_escapes_content_recomputes_hashes_and_refuses_overwrite(tmp_path, monkeypatch):
    before, after = pair(), pair((10, 0, 0))
    before["design"]["title"] = '<script src="https://example.org/evil"></script>'
    sealed(before)
    monkeypatch.setattr(socket, "socket", lambda *_a, **_kw: pytest.fail("Network used"))
    destination = export_comparison(before, after, tmp_path / "comparison")
    result = json.loads((destination / "comparison.json").read_text(encoding="utf-8"))
    for side in ("before", "after"):
        assert digest(load_blueprint(destination / f"{side}.json")) == result[side]["snapshot_sha256"]
    report = (destination / "report.html").read_text(encoding="utf-8")
    assert "<script" not in report and "&lt;script" in report
    assert "default-src 'none'" in report and 'href="comparison.json"' in report
    assert 'role="region" tabindex="0"' in report and "Tables scroll sideways" in report
    original = {p.name: p.read_bytes() for p in destination.iterdir()}
    with pytest.raises(FileExistsError):
        export_comparison(before, after, destination)
    assert {p.name: p.read_bytes() for p in destination.iterdir()} == original
    with pytest.raises(ValueError, match="same maker"):
        export_comparison(before, document("project"), tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_cli_results_and_project_comparison_are_offline_and_preserve_history(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(socket, "socket", lambda *_a, **_kw: pytest.fail("Network used"))
    before, after = pair((15, 0, 0)), pair((12, 0, 0))
    before["request"]["acceptance_rules"] = [limit()]
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    save_blueprint(before, a)
    save_blueprint(after, b)
    db = tmp_path / "must-not-exist.db"
    assert main(["--database", str(db), "compare", str(a), str(b), "--results"]) == 0
    assert json.loads(capsys.readouterr().out)["acceptance"]["outcomes"] == {"regressed": 1}
    assert not db.exists()
    assert main(["compare", str(a), str(b), "--output", str(tmp_path / "export")]) == 0
    assert json.loads(capsys.readouterr().out)["directory"].endswith("export")
    path = tmp_path / "history.ffproject.json"
    project = create_project(path, "History", before)
    append_revision(path, after, expected_head=head(project))
    original = path.read_bytes()
    assert main(["project-compare", str(path), "1", "2"]) == 0
    assert json.loads(capsys.readouterr().out)["acceptance"]["outcomes"] == {"regressed": 1}
    assert path.read_bytes() == original and len(load_project(path)["revisions"]) == 2
    with pytest.raises(SystemExit) as exc:
        main(["project-compare", str(path), "0", "2"])
    assert exc.value.code == 2 and path.read_bytes() == original
