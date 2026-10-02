"""Portable offline revision report and independently reopenable source snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from fieldforge.blueprints.comparison import compare_results, comparison_text
from fieldforge.blueprints.render import _atomic, esc, normalized_document, save_blueprint


def _table(headers, rows):
    return (f'<div class="table" role="region" tabindex="0" '
            f'aria-label="{esc(headers[0])} comparison; scroll horizontally if needed"><table><thead><tr>' +
            "".join(f'<th scope="col">{esc(cell)}</th>' for cell in headers) +
            '</tr></thead><tbody>' + "".join('<tr>' +
            "".join(f'<td>{esc(cell)}</td>' for cell in row) + '</tr>' for row in rows) +
            '</tbody></table></div>')


def _rule_text(rule):
    if rule is None:
        return "Absent"
    value = str(rule["value"]).replace("_", " ") if rule["metric"] == "pair.relation" else str(rule["value"])
    unit = "" if rule["unit"] == "text" else " " + rule["unit"]
    return f'{rule["label"]}: {rule["metric"]} {rule["target"]} {rule["operator"]} {value}{unit}'


def _actual_text(row):
    if row["actual"] is None:
        return row["status"] + ": " + row["detail"]
    value = str(row["actual"])
    if row["metric"] == "pair.relation":
        value = value.replace("_", " ")
    approx = "approximately " if row.get("actual_is_rounded") else ""
    unit = "" if row["unit"] == "text" else " " + row["unit"]
    return f'{row["status"]}: {approx}{value}{unit}'


def _overview(result):
    acceptance = result["acceptance"]
    counts = acceptance["outcomes"]
    body = ('<section aria-labelledby="fixed"><h2 id="fixed">Fixed baseline requirements</h2>'
            '<div class="counts">' + "".join(
                f'<p><strong>{number}</strong>{esc(label)}</p>' for number, label in (
                    (acceptance["baseline_count"], "Baseline limits"),
                    (counts.get("regressed", 0), "Regressed"),
                    (counts.get("now_passes", 0), "Now pass"),
                    (len(acceptance["rule_changes"]), "Rule changes"))) + '</div>')
    if acceptance["fixed_baseline"]:
        body += _table(("Requirement", "Unchanged criterion", "Before", "After", "Outcome"), (
            (f'{row["id"]} — {row["rule"]["label"]}',
             f'{row["rule"]["metric"]} {row["rule"]["target"]} {row["rule"]["operator"]} '
             f'{row["rule"]["value"]} {row["rule"]["unit"]}',
             _actual_text(row["before"]), _actual_text(row["after"]), row["outcome"].replace("_", " "))
            for row in acceptance["fixed_baseline"]))
    else:
        body += '<p>No baseline limits were recorded. No acceptance improvement can be established.</p>'
    body += '</section><section aria-labelledby="rules"><h2 id="rules">Rule changes</h2>'
    body += ('<p>Removed or changed rules remain in the fixed baseline above.</p>' +
             _table(("ID", "Change", "Before", "After"), (
                 (row["id"], row["change"].replace("_", " "), _rule_text(row["before"]), _rule_text(row["after"]))
                 for row in acceptance["rule_changes"])) if acceptance["rule_changes"] else '<p>No rule changes.</p>')
    body += '</section>'
    if "geometry" not in result:
        return body
    geometry = result["geometry"]
    body += '<section aria-labelledby="geometry"><h2 id="geometry">Engineering envelope changes</h2>'
    body += _table(("Measurement", "Before", "After"), (
        (label, geometry["before"][key], geometry["after"][key]) for key, label in (
            ("status", "Analysis status"), ("part_count", "Parts"), ("overlap_pairs", "Overlapping pairs"),
            ("face_contact_pairs", "Face contacts"), ("connected_groups", "Touching/overlapping groups"))
        # Unresolved analysis has placeholder zero counts, not measured zeroes.
        if key in ("status", "part_count") or geometry["status"] == "compared"))
    body += _table(("Overall span (mm)", "Before", "After"), (
        (axis, geometry["span_before_mm"][i] if geometry["span_before_mm"] else "unresolved",
         geometry["span_after_mm"][i] if geometry["span_after_mm"] else "unresolved")
        for i, axis in enumerate("XYZ")))
    if geometry["status"] != "compared":
        body += '<p>Pair changes cannot be determined. Unresolved geometry is not a clean result.</p>'
    elif geometry["pairs"]:
        def measurement(pair):
            if pair is None:
                return "Absent"
            approx = "approximately " if pair["clearance_is_rounded"] else ""
            return (pair["relation"].replace("_", " ") + '; ' + approx + pair["clearance_mm"] + ' mm')
        body += _table(("Pair", "Before", "After", "Clearance direction"), (
            (" / ".join(row["part_ids"]), measurement(row["before"]), measurement(row["after"]),
             row["clearance_change"].replace("_", " ")) for row in geometry["pairs"][:200]))
        if len(geometry["pairs"]) > 200:
            body += f'<p>{len(geometry["pairs"]) - 200} additional pair changes are in comparison.json.</p>'
    else:
        body += '<p>No pair measurements changed.</p>'
    return body + '</section>'


def export_comparison(before, after, destination):
    before, after = normalized_document(before), normalized_document(after)
    result = compare_results(before, after)
    destination = Path(destination)
    # Never overwrite a previous comparison or source directory, even if empty.
    destination.mkdir(parents=True, exist_ok=False)
    save_blueprint(before, destination / "before.json")
    save_blueprint(after, destination / "after.json")
    _atomic(destination / "comparison.json", json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    _atomic(destination / "report.html", '<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
            '<title>FieldForge revision comparison</title><style>'
            'body{font:16px/1.55 system-ui,sans-serif;max-width:78rem;margin:auto;padding:1.5rem;color:#132536;background:#fff}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;border-left:4px solid #38698a;padding:1rem}'
            'a{color:#125486}code{overflow-wrap:anywhere}h1{font-size:2rem}h2{margin-top:2rem}'
            '.counts{display:flex;flex-wrap:wrap;gap:1rem}.counts p{background:#edf3f7;padding:1rem;margin:0;min-width:7rem}'
            '.counts strong{display:block;font-size:2rem}.table{overflow:auto}.table:focus{outline:2px solid #125486;outline-offset:2px}'
            '.scroll-hint{display:none}table{border-collapse:collapse;width:100%;margin:1rem 0;table-layout:fixed}'
            'th,td{text-align:left;vertical-align:top;padding:.65rem;border-bottom:1px solid #c5d2dc;overflow-wrap:anywhere}'
            'th{background:#edf3f7}summary{cursor:pointer;font-weight:bold;padding:1rem 0}'
            '@media(max-width:600px){body{padding:1rem}table{min-width:580px}.scroll-hint{display:block}.counts{gap:.5rem}.counts p{min-width:5rem}}'
            '@media print{body{padding:0}a{color:inherit}thead{display:table-header-group}tr{break-inside:avoid}}'
            '</style><main><h1>FieldForge revision comparison</h1>'
            '<p>Offline, deterministic checks. Design drafts require review.</p>'
            f'<p><strong>Before:</strong> {esc(result["before"]["title"])}<br>'
            f'<strong>After:</strong> {esc(result["after"]["title"])}</p>'
            '<p><a href="before.json">Before snapshot</a> · <a href="after.json">After snapshot</a> · '
            '<a href="comparison.json">Complete comparison JSON</a></p>'
            f'<p>Before snapshot SHA-256: <code>{esc(result["before"]["snapshot_sha256"])}</code><br>'
            f'After snapshot SHA-256: <code>{esc(result["after"]["snapshot_sha256"])}</code></p>'
            f'<p>{esc(result["scope"])}</p>'
            '<p class="scroll-hint">Tables scroll sideways to reveal all columns. Swipe, or focus a table and use the arrow keys.</p>'
            f'{_overview(result)}'
            '<details><summary>Full readable comparison: dimensions, gaps, checks and field changes</summary>'
            f'<pre>{esc(comparison_text(result))}</pre></details></main></html>')
    _atomic(destination / "README.txt",
            "FieldForge offline revision comparison\n\nOpen report.html in a browser. No server or model is required.\n"
            "comparison.json contains all changed geometry pairs; the readable view shows at most 200.\n"
            "before.json and after.json are complete, reopenable snapshots with freshly computed checks.\n"
            "Snapshot hashes use FieldForge's canonical JSON digest (sorted keys, compact separators, UTF-8), "
            "not the pretty-printed file bytes. Source project files are not modified.\n"
            "Changing or removing a current rule never changes the fixed baseline comparison.\n"
            "No overall improvement, fabrication readiness or engineering certification is asserted.\n"
            "An interrupted export may leave an incomplete folder; retry using a new destination.\n")
    return destination
