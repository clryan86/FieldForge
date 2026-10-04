"""Dimensioned envelope sheets and schedules derived only from recorded design data.

Each part is one axis-aligned rectangular instance. No joints, tolerances, hidden
surfaces, stock allowances or fabrication operations are inferred here.
"""

from __future__ import annotations

import csv
import html
import io
import math
import textwrap

VIEWS = (("top", (0, 1)), ("front", (0, 2)), ("side", (1, 2)))
INK = "#18344c"
LINE = "#426986"


def _escape(value):
    return html.escape(str(value), quote=True)


def number(value):
    """Keep the recorded numeric precision in labels and machine-readable schedules."""
    return str(int(value)) if value == int(value) else str(value)


def _triple(values):
    return " × ".join(number(v) for v in values)


def _text(x, y, value, size=14, anchor="start"):
    return (f'<text x="{x:.4f}" y="{y:.4f}" text-anchor="{anchor}" '
            f'fill="{INK}" style="font-size:{size}px">{_escape(value)}</text>')


def _line(x1, y1, x2, y2, **attributes):
    extra = "".join(f' {key.replace("_", "-")}="{_escape(value)}"'
                    for key, value in attributes.items())
    return (f'<line class="line" x1="{x1:.4f}" y1="{y1:.4f}" '
            f'x2="{x2:.4f}" y2="{y2:.4f}" stroke="{LINE}"{extra}/>')


def _sheet(title, body, sheet, fingerprint, description):
    # Bounded wrapping preserves full titles without colliding with the sheet number.
    title_rows = textwrap.wrap(" ".join(title.split()), width=92)
    heading = "".join(_text(28, 31 + i * 24, row, 19)
                      for i, row in enumerate(title_rows))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1100 780" data-font="mono" '
        f'role="img" aria-label="{_escape(title)}">'
        f'<title>{_escape(title)}</title><desc>{_escape(description)}</desc>'
        '<rect width="100%" height="100%" fill="#ffffff"/>'
        f'<style>text{{font:14px monospace;fill:{INK}}}'
        '.part{fill:#dceaf3;fill-opacity:.55;stroke:#426986;stroke-width:1.5}'
        '.line{stroke-width:1;fill:none}</style>'
        + heading + body
        + _line(24, 693, 1076, 693)
        + _text(28, 715, "DESIGN DRAFT • Rectangular envelopes; joints, tolerances and load ratings unspecified.", 13)
        + _text(28, 736, "Units: mm • Fit to sheet; use dimension values. Do not measure printed or screen geometry.", 13)
        + _text(28, 759, f"{sheet} • Design SHA-256 {fingerprint[:16]}", 12)
        + '</svg>'
    )


def bounds(parts):
    """Return minimum corner and occupied span, excluding unused origin space."""
    origin = [min((p["position_mm"][a] for p in parts), default=0) for a in range(3)]
    span = [max(((p["position_mm"][a] - origin[a]) + p["size_mm"][a]
                 for p in parts), default=0) for a in range(3)]
    return origin, span


def _dimensions(x, y, width, height, horizontal, vertical):
    """Outside extension lines and ticks, with labels on separate reserved rows."""
    bottom, right = y + height + 26, x + width + 26
    result = []
    for edge in (x, x + width):
        result.extend((_line(edge, y + height + 5, edge, bottom + 6),
                       _line(edge - 4, bottom + 4, edge + 4, bottom - 4)))
    result.extend((_line(x, bottom, x + width, bottom),
                   _text(x + width / 2, bottom + 22, horizontal, anchor="middle")))
    for edge in (y, y + height):
        result.extend((_line(x + width + 5, edge, right + 6, edge),
                       _line(right - 4, edge + 4, right + 4, edge - 4)))
    result.extend((_line(right, y, right, y + height),
                   # A horizontal label above the vertical dimension avoids rotated
                   # text and remains readable in the native desktop preview.
                   _text(right, y - 14, vertical, anchor="middle")))
    return "".join(result)


def _projection(parts, axes, box, *, labels=False):
    a, b = axes
    left, top, area_width, area_height = box
    origin, span = bounds(parts)
    scale = min(area_width / max(span[a], 1e-6), area_height / max(span[b], 1e-6))
    width, height = span[a] * scale, span[b] * scale
    left += (area_width - width) / 2
    top += (area_height - height) / 2
    body = []
    for index, part in enumerate(parts, 1):
        x = left + (part["position_mm"][a] - origin[a]) * scale
        y = top + height - (part["position_mm"][b] - origin[b] + part["size_mm"][b]) * scale
        w, h = part["size_mm"][a] * scale, part["size_mm"][b] * scale
        body.append(f'<rect class="part" data-part="{_escape(part["id"])}" '
                    f'x="{x:.4f}" y="{y:.4f}" width="{w:.4f}" height="{h:.4f}">'
                    f'<title>{_escape(part["id"] + ": " + part["name"])}; '
                    f'{_escape(_triple(part["size_mm"]))} mm</title></rect>')
        if labels and w >= 35 and h >= 25:
            body.append(_text(x + 5, y + 18, str(index), size=12))
    body.append(_dimensions(left, top, width, height,
                            f'{"XYZ"[a]}: {number(span[a])} mm',
                            f'{"XYZ"[b]}: {number(span[b])} mm'))
    return "".join(body)


def _isometric(parts):
    if not parts:
        return _text(40, 200, "No parts recorded.")
    origin, _ = bounds(parts)

    def project(point):
        x, y, z = point
        return (math.sqrt(3) / 2 * (x - y), (x + y) / 2 - z)

    faces = []
    # Transparent envelopes intentionally retain all edges: no hidden-surface or
    # collision inference. Face order is deterministic, not a visibility solver.
    for part in parts:
        p, s = part["position_mm"], part["size_mm"]
        vertices = [project([(p[a] - origin[a]) + bit[a] * s[a] for a in range(3)])
                    for bit in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                                (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))]
        faces.extend((part, [vertices[i] for i in face]) for face in
                     ((0, 1, 2, 3), (0, 1, 5, 4), (1, 2, 6, 5),
                      (2, 3, 7, 6), (3, 0, 4, 7), (4, 5, 6, 7)))
    points = [point for _, face in faces for point in face]
    low = [min(p[a] for p in points) for a in range(2)]
    span = [max(p[a] for p in points) - low[a] for a in range(2)]
    scale = min(820 / max(span[0], 1e-6), 420 / max(span[1], 1e-6))
    offset = [140 + (820 - span[0] * scale) / 2, 165 + (420 - span[1] * scale) / 2]
    body = []
    for part, face in faces:
        coords = " ".join(f'{offset[0] + (x - low[0]) * scale:.4f},'
                          f'{offset[1] + (y - low[1]) * scale:.4f}' for x, y in face)
        body.append(f'<polygon class="part" data-part="{_escape(part["id"])}" '
                    f'points="{coords}" style="fill:none"><title>'
                    f'{_escape(part["id"] + ": " + part["name"])}</title></polygon>')
    for x, y, label in ((83, 638, "+X"), (27, 638, "+Y"), (55, 589, "+Z")):
        body.extend((_line(55, 622, x, y), _text(x, y - 6, label, 12)))
    body.append(_text(145, 650, "Wireframe reference • All envelope edges shown, including obscured edges."))
    return "".join(body)


def engineering_drawings(design, fingerprint):
    parts = design["parts"]
    origin, span = bounds(parts)
    files = {}
    description = (f'Assembly occupied span XYZ: {_triple(span)} mm. '
                   f'Minimum corner XYZ: {_triple(origin)} mm. '
                   'Each part is one rectangular instance. Full parts schedule is in the report.')
    for name, axes in VIEWS:
        body = _text(28, 94, name.upper() + f' • {"XYZ"[axes[0]]} right / {"XYZ"[axes[1]]} up', 16)
        body += _text(28, 119, "Numbers refer to the parts schedule; small or obscured parts may have no visible number.", 13)
        body += (_projection(parts, axes, (120, 180, 730, 390), labels=True) if parts
                 else _text(40, 220, "No parts recorded. Add dimensioned parts to generate geometry."))
        body += _text(28, 672, f"Minimum corner XYZ: {_triple(origin)} mm", 13)
        files[f"{name}.svg"] = _sheet(design["title"], body, name.upper(), fingerprint, description)
    body = _text(28, 94, "ISOMETRIC • Assembly envelope reference", 16) + _isometric(parts)
    files["isometric.svg"] = _sheet(design["title"], body, "ISOMETRIC", fingerprint, description)
    for index, part in enumerate(parts, 1):
        body = _text(28, 94, f'{index:03d} • {part["id"]} • ONE INSTANCE', 16)
        for field, start in (("name", 119), ("material", 157)):
            for i, row in enumerate(textwrap.wrap(f'{field.title()}: {part[field]}', width=110)):
                body += _text(28, start + i * 18, row)
        for (name, axes), left in zip(VIEWS, (45, 395, 745)):
            body += _text(left, 220, name.upper() + f' • {"XYZ"[axes[0]]}/{"XYZ"[axes[1]]}', 15)
            # Three independently fitted projections, each with both dimensions.
            body += _projection([part], axes, (left, 280, 180, 210))
        body += _text(28, 580, f'XYZ size: {_triple(part["size_mm"])} mm')
        body += _text(28, 610, f'XYZ minimum-corner position: {_triple(part["position_mm"])} mm')
        evidence = ", ".join(part["source_ids"]) or "None; assumption"
        if len(evidence) > 100:
            evidence = evidence[:76] + "… (full list in report)"
        body += _text(28, 640, 'Evidence IDs: ' + evidence)
        body += _text(28, 670, "Envelope dimensions only. Material quantities and specifications appear separately in the report.", 13)
        files[f"part-{index:03d}.svg"] = _sheet(
            design["title"], body, f'PART {index:03d} / {len(parts):03d}', fingerprint,
            f'{part["id"]}: {part["name"]}. Material: {part["material"]}. '
            f'Size XYZ {_triple(part["size_mm"])} mm. '
            f'Position XYZ {_triple(part["position_mm"])} mm.')
    return files


PART_COLUMNS = ("item", "part_id", "name", "material", "instances", "size_x_mm", "size_y_mm",
                "size_z_mm", "position_x_mm", "position_y_mm", "position_z_mm", "source_ids", "sheet")
MATERIAL_COLUMNS = ("item", "name", "quantity", "unit", "specification", "part_ids", "source_ids")


def schedules(design):
    """Do not aggregate similar parts or reinterpret model-recorded material units."""
    parts = [[i, p["id"], p["name"], p["material"], 1,
              *(number(v) for v in p["size_mm"]), *(number(v) for v in p["position_mm"]),
              "; ".join(p["source_ids"]), f"part-{i:03d}.svg"]
             for i, p in enumerate(design["parts"], 1)]
    materials = [[i, m["name"], number(m["quantity"]), m["unit"], m["specification"],
                  "; ".join(m["part_ids"]), "; ".join(m["source_ids"])]
                 for i, m in enumerate(design["materials"], 1)]
    return (("parts", PART_COLUMNS, parts), ("materials", MATERIAL_COLUMNS, materials))


def _csv_cell(value):
    value = str(value)
    # Leading whitespace/control characters can hide a spreadsheet formula.
    # CSV quoting alone does not prevent formula evaluation by spreadsheet apps.
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def schedule_csvs(design):
    files = {}
    for name, columns, rows in schedules(design):
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\r\n")
        writer.writerow(columns)
        writer.writerows([_csv_cell(cell) for cell in row] for row in rows)
        files[name + ".csv"] = stream.getvalue()
    return files


def schedule_html(design):
    result = ['<h2>Parts and materials schedules</h2><p>One part row means one placed instance. '
              'Material quantities retain the recorded units; they are not an inferred stock or cut list. '
              'XYZ dimensions and minimum-corner positions are in millimetres.</p>']
    for name, columns, rows in schedules(design):
        result.append(f'<div class="schedule"><table><caption>{name.title()}</caption><thead><tr>')
        result.extend(f'<th scope="col">{_escape(c.replace("_", " "))}</th>' for c in columns)
        result.append('</tr></thead><tbody>')
        for row in rows:
            result.append('<tr>' + ''.join(f'<td>{_escape(cell)}</td>' for cell in row) + '</tr>')
        result.append('</tbody></table></div>')
    return "".join(result)
