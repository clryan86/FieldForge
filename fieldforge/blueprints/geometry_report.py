"""Readable offline geometry reports and machine-readable pair schedules."""

import csv
import html
import io


def geometry_csv(analysis):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(("analysis_status", "part_a", "part_b", "relation", "overlap_x_mm", "overlap_y_mm", "overlap_z_mm",
                     "gap_x_mm", "gap_y_mm", "gap_z_mm", "clearance_mm", "clearance_squared_mm2",
                     "clearance_is_rounded", "note"))
    # All cells are schema-validated IDs, fixed relation keys or nonnegative decimal
    # strings. No user prose or executable spreadsheet expressions enter this CSV.
    for row in analysis["pairs"]:
        writer.writerow(("analyzed", *row["part_ids"], row["relation"], *row["overlap_mm"], *row["gap_mm"],
                         row["clearance_mm"], row["clearance_squared_mm2"], row["clearance_is_rounded"], ""))
    if not analysis["pairs"]:
        summary = analysis["summary"]
        writer.writerow((summary["status"], *("" for _ in range(12)),
                         " ".join(summary["problems"]) or "One part; no pairs to inspect."))
    return output.getvalue()


def geometry_html(analysis):
    def esc(value):
        return html.escape(str(value), quote=True)
    summary = analysis["summary"]
    result = ['<h2>Envelope geometry inspection</h2><p>' + esc(summary["scope"]) + '</p>']
    if summary["status"] != "analyzed":
        return "".join(result) + '<p>Unresolved: ' + esc(" ".join(summary["problems"])) + '</p>'
    result.append('<p>' + esc(f'{summary["pair_count"]} pairs inspected; '
                              f'{summary["overlap_pairs"]} overlap; '
                              f'{summary["face_contact_pairs"]} face contacts; '
                              f'{summary["edge_contact_pairs"]} edge contacts; '
                              f'{summary["point_contact_pairs"]} point contacts; '
                              f'{summary["separated_pairs"]} separated pairs.') + '</p>')
    result.append('<p>Touching/overlapping groups: ' + esc(summary["connected_groups"]) + '</p><ul>')
    result.extend('<li>' + esc(", ".join(group)) + '</li>' for group in summary["groups"])
    result.append('</ul><p>Per-axis overlap and gap lengths below are decimal millimetres. '
                  'A positive overlap on one axis alone is not a volume intersection. '
                  'All pairs, including separations and shortest clearances, are included in geometry.csv and geometry.json. '
                  'Clearance displays can be rounded; acceptance compares squared distances exactly.</p>')
    involved = [p for p in analysis["pairs"] if p["relation"] != "separated"]
    if not involved:
        return "".join(result) + '<p>No touching or overlapping pairs.</p>'
    result.append('<div class="schedule"><table><caption>Touching and overlapping envelopes</caption>'
                  '<thead><tr><th scope="col">Parts</th><th scope="col">Relation</th>'
                  '<th scope="col">Overlap XYZ (mm)</th><th scope="col">Gap XYZ (mm)</th></tr></thead><tbody>')
    for pair in involved:
        values = (" / ".join(pair["part_ids"]), pair["relation"].replace("_", " "),
                  " / ".join(pair["overlap_mm"]), " / ".join(pair["gap_mm"]))
        result.append('<tr>' + ''.join('<td>' + esc(v) + '</td>' for v in values) + '</tr>')
    result.append('</tbody></table></div>')
    return "".join(result)
