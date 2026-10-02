"""Deterministic offline drawings and portable design reports; never run model code."""

from __future__ import annotations

import html
import json
import os
import re
import tempfile
from pathlib import Path

from fieldforge.blueprints.checks import check_design
from fieldforge.blueprints.engine import BlueprintRequest, digest
from fieldforge.blueprints.schema import REVIEW_SCHEMA, validate


def esc(value):
    return html.escape(str(value), quote=True)


def _svg(title, body, width=1100, height=740):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{esc(title)}">'
        '<rect width="100%" height="100%" fill="#102239"/>'
        '<style>text{font:14px sans-serif;fill:#eff6ff}.part{fill:#28496a;'
        'fill-opacity:.4;stroke:#91caff;stroke-width:1.5}.line{stroke:#87b8d8;'
        'stroke-width:1.5;fill:none}</style>'
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" '
        'orient="auto"><path d="M0 0 L8 4 L0 8 Z" fill="#87b8d8"/></marker></defs>'
        f'<text x="24" y="30" style="font-size:20px">{esc(title[:100])}</text>'
        f'{body}<text x="24" y="{height - 16}" style="font-size:12px">'
        'DESIGN DRAFT · verify assumptions and source evidence before use</text></svg>'
    )


def _engineering(design):
    files = {}
    parts = design["parts"]
    for name, axes in (("top", (0, 1)), ("front", (0, 2)), ("side", (1, 2))):
        a, b = axes
        max_a = max((p["position_mm"][a] + p["size_mm"][a] for p in parts), default=1)
        max_b = max((p["position_mm"][b] + p["size_mm"][b] for p in parts), default=1)
        scale = min(870 / max(max_a, 1), 490 / max(max_b, 1))
        body = []
        for index, part in enumerate(parts):
            x = 90 + part["position_mm"][a] * scale
            y = 590 - (part["position_mm"][b] + part["size_mm"][b]) * scale
            w, h = part["size_mm"][a] * scale, part["size_mm"][b] * scale
            body.append(f'<rect class="part" x="{x:.4f}" y="{y:.4f}" width="{w:.4f}" '
                        f'height="{h:.4f}"><title>{esc(part["name"])} '
                        f'{esc(part["size_mm"])} mm</title></rect>')
            body.append(f'<text x="{x + 4:.4f}" y="{y + 16:.4f}">{esc(part["id"])}</text>')
            # Alternate dimension label baselines to reduce collisions for adjoining parts.
            baseline = 612 + (index % 3) * 18
            body.append(f'<path class="line" d="M{x:.4f} {baseline} h{w:.4f}"/>')
            body.append(f'<text x="{x:.4f}" y="{baseline + 14}">'
                        f'{esc(part["id"])}: {part["size_mm"][a]:g} mm</text>')
        body.append('<text x="24" y="68">Rectangular part envelopes; not fabrication geometry.</text>')
        body.append(f'<text x="24" y="90">Extent: {max_a:g} × {max_b:g} mm. '
                    'Scale fits page; use dimensions, not print scaling.</text>')
        files[f"{name}.svg"] = _svg(design["title"] + " — " + name, "".join(body))
    return files


def _project(design, validation):
    schedule = validation["schedule"]
    if not schedule:
        return {"schedule.svg": _svg("Schedule needs revision", "")}
    maximum = max(row["end"] for row in schedule)
    names = {p["id"]: p["name"] for p in design["phases"]}
    body = ['<text x="280" y="65">Relative days from project start; dependencies only</text>']
    height = max(400, 130 + len(schedule) * 48)
    for index, row in enumerate(schedule):
        y = 95 + index * 48
        x = 280 + 680 * row["start"] / maximum
        width = 680 * (row["end"] - row["start"]) / maximum
        body.append(f'<text x="24" y="{y + 20}">{esc((row["id"] + ": " + names[row["id"]])[:30])}</text>')
        body.append(f'<rect class="part" x="{x:.2f}" y="{y}" width="{max(1, width):.2f}" height="28"/>')
        body.append(f'<text x="{x + 5:.2f}" y="{y + 20}">{row["start"]:g}–{row["end"]:g}d</text>')
    guide = []
    for index, step in enumerate(design["steps"]):
        y = 90 + index * 110
        guide.append(f'<rect class="part" x="40" y="{y}" width="1000" height="90" rx="8"/>')
        labels = (step["id"] + " — " + step["title"], step["instructions"],
                  "After: " + (", ".join(step["depends_on"]) or "Start") +
                  " | Evidence: " + (", ".join(step["source_ids"]) or "Assumption"))
        for offset, label in enumerate(labels):
            guide.append(f'<text x="58" y="{y + 24 + 26 * offset}">{esc(label[:115])}</text>')
    guide.append('<text x="24" y="64">Step overview; full instructions and acceptance checks appear in the report.</text>')
    return {
        "schedule.svg": _svg(design["title"] + " — dependency schedule", "".join(body), height=height),
        "guide.svg": _svg(design["title"] + " — illustrated guide", "".join(guide),
                          height=max(350, 140 + len(design["steps"]) * 110)),
    }


def _software(design):
    components = design["components"]
    positions = {row["id"]: (55 + (i % 3) * 350, 100 + (i // 3) * 180)
                 for i, row in enumerate(components)}
    legend_y = 160 + ((len(components) + 2) // 3) * 180
    height = max(500, legend_y + 65 + len(design["connections"]) * 30)
    body = []
    for index, edge in enumerate(design["connections"], 1):
        if edge["source"] not in positions or edge["target"] not in positions:
            continue
        sx, sy = positions[edge["source"]]
        tx, ty = positions[edge["target"]]
        if sy == ty and sx != tx:
            start = (sx + 285 if tx > sx else sx, sy + 48)
            end = (tx if tx > sx else tx + 285, ty + 48)
            route = f'M{start[0]} {start[1]} L{end[0]} {end[1]}'
            lx, ly = (start[0] + end[0]) / 2 - 8, start[1] - 10
        else:
            start = (sx + 140, sy + 95 if ty >= sy else sy)
            end = (tx + 140, ty if ty > sy else ty + 95)
            lane = start[1] + (30 if ty >= sy else -30)
            route = (f'M{start[0]} {start[1]} L{start[0]} {lane} '
                     f'L{end[0]} {lane} L{end[0]} {end[1]}')
            lx, ly = start[0] + 8, lane - 6
        body.append(f'<path class="line" marker-end="url(#arrow)" d="{route}"/>')
        body.append(f'<text x="{lx}" y="{ly}">E{index}</text>')
        label = f'E{index}: {edge["source"]} → {edge["target"]} | {edge["protocol"]}'
        body.append(f'<text x="24" y="{legend_y + index * 30}">{esc(label[:125])}</text>')
    for row in components:
        x, y = positions[row["id"]]
        body.append(f'<rect class="part" x="{x}" y="{y}" width="285" height="95" rx="8"/>')
        for index, label in enumerate((row["id"], row["name"][:32], "Trust: " + row["trust_zone"][:27])):
            body.append(f'<text x="{x + 12}" y="{y + 24 + index * 25}">{esc(label)}</text>')
    return {"architecture.svg": _svg(design["title"] + " — system architecture", "".join(body), height=height)}


def drawings(blueprint):
    mode, design = blueprint["request"]["mode"], blueprint["design"]
    validation = check_design(mode, design, {s["id"] for s in blueprint["sources"]})
    if mode == "engineering":
        return _engineering(design)
    if mode == "project":
        return _project(design, validation)
    return _software(design)


def validate_document(value):
    if (not isinstance(value, dict) or value.get("format") != "fieldforge-blueprint"
            or type(value.get("version")) is not int or value["version"] != 1):
        raise ValueError("Unsupported blueprint document.")
    required = {"format", "version", "created_at", "model", "request", "design", "design_sha256",
                "sources", "validation", "review", "review_error", "attempts", "status"}
    if set(value) != required:
        raise ValueError("Missing or unexpected blueprint fields.")
    for field in ("created_at", "model", "review_error"):
        if not isinstance(value[field], str) or len(value[field]) > 6000:
            raise ValueError("Invalid blueprint metadata.")
    if value["status"] not in {"draft", "needs_revision"}:
        raise ValueError("A blueprint can only be a draft or need revision.")
    request = BlueprintRequest(**value["request"])
    if digest(value["design"]) != value["design_sha256"]:
        raise ValueError("Blueprint design checksum mismatch.")
    sources = value["sources"]
    if not isinstance(sources, list) or not 1 <= len(sources) <= 8:
        raise ValueError("Invalid blueprint sources.")
    ids = set()
    for source in sources:
        if (not isinstance(source, dict) or not isinstance(source.get("id"), str)
                or not re.fullmatch(r"S[1-8]", source["id"])):
            raise ValueError("Invalid blueprint source.")
        if source["id"] in ids:
            raise ValueError("Duplicate blueprint source.")
        ids.add(source["id"])
        for field in ("title", "passage", "source_url", "checksum", "license"):
            if not isinstance(source.get(field), str) or len(source[field]) > 6000:
                raise ValueError("Invalid source metadata.")
        if not re.fullmatch(r"[0-9a-f]{64}", source["checksum"]):
            raise ValueError("Invalid source checksum.")
    if value["review"] is not None:
        validate(value["review"], REVIEW_SCHEMA)
        if any(set(row["source_ids"]) - ids for row in value["review"]["findings"]):
            raise ValueError("Review references unknown evidence.")
    if not isinstance(value["attempts"], list) or len(value["attempts"]) > 2:
        raise ValueError("Invalid generation history.")
    return check_design(request.mode, value["design"], ids)


def normalized_document(value):
    """Never trust a stored status or computed result, even if JSON was hand-edited."""
    validation = validate_document(value)
    review = value["review"]
    needs_revision = (validation["status"] == "needs_revision" or bool(value["review_error"])
                      or review is None or bool(review["missing_information"])
                      or any(f["severity"] == "blocking" for f in review["findings"]))
    return {**value, "validation": validation,
            "status": "needs_revision" if needs_revision else "draft"}


def readable(value, indent=0):
    """Readable plain text shared by the accessible desktop result view and reports."""
    if isinstance(value, dict):
        return "\n".join(" " * indent + key.replace("_", " ").capitalize() + ": " +
                         ("\n" + readable(item, indent + 2) if isinstance(item, (dict, list))
                          else str(item)) for key, item in value.items())
    if isinstance(value, list):
        return "\n".join(" " * indent + "• " + readable(item, indent + 2).lstrip()
                         for item in value) or "None recorded."
    return str(value)


def _content_html(value):
    if isinstance(value, dict):
        return "<dl>" + "".join("<dt>" + esc(k.replace("_", " ").capitalize()) +
                                 "</dt><dd>" + _content_html(v) + "</dd>"
                                 for k, v in value.items()) + "</dl>"
    if isinstance(value, list):
        return "<ul>" + "".join("<li>" + _content_html(v) + "</li>" for v in value) + "</ul>" if value else "None recorded."
    return esc(value).replace("\n", "<br>")


def report_html(blueprint):
    blueprint = normalized_document(blueprint)
    validation = blueprint["validation"]
    design = blueprint["design"]
    images = drawings(blueprint)
    sections = [
        "<h1>" + esc(design["title"]) + "</h1>",
        '<p class="notice">Design draft — not independently verified or certified. '
        'The model critique is not an engineering review.</p>',
        "<p>" + esc(design["summary"]) + "</p>",
        "<p>Status: <strong>" + esc(blueprint["status"].replace("_", " ")) + "</strong></p>",
        "<h2>Request and constraints</h2>" + _content_html(blueprint["request"]),
    ]
    sections.extend(images.values())
    for name, content in design.items():
        if name in {"title", "summary"}:
            continue
        sections.append("<h2>" + esc(name.replace("_", " ").title()) + "</h2>")
        for row in content:
            sections.append('<section class="card">' + _content_html(row) + "</section>")
        if not content:
            sections.append("<p>None recorded.</p>")
    sections.append("<h2>Recomputed deterministic checks</h2>" + _content_html(validation))
    sections.append("<h2>Model critique (not independent verification)</h2>" +
                    _content_html(blueprint.get("review") or "Review unavailable."))
    if blueprint.get("review_error"):
        sections.append("<p>Review incomplete: " + esc(blueprint["review_error"]) + "</p>")
    sections.append("<h2>Local source excerpts</h2>")
    for source in blueprint["sources"]:
        sections.append("<h3>" + esc(source["id"] + " — " + source["title"]) + "</h3>"
                        '<section class="card">' + _content_html(source) + "</section>")
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>" + esc(design["title"]) + "</title>"
        "<style>body{font:16px/1.55 system-ui,sans-serif;max-width:1100px;margin:36px auto;"
        "padding:0 24px;color:#17314b;background:#fafcff}h1{font-size:34px}h2{margin-top:36px}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.6 ui-monospace,monospace;"
        "padding:16px;background:#eaf1f7;border-radius:8px}svg{width:100%;height:auto;margin:20px 0}"
        ".notice{padding:16px;background:#fff0c2;border-left:4px solid #a06c00}"
        ".card{margin:16px 0;padding:16px 22px;background:#eaf1f7;border-radius:8px}"
        "dl{display:grid;grid-template-columns:minmax(100px,180px) 1fr;gap:8px 20px}"
        "dt{font-weight:600}dd{margin:0;white-space:normal;overflow-wrap:anywhere}"
        "ul{padding-left:20px;margin:0}li{margin-bottom:8px}"
        "@media(max-width:600px){dl{display:block}dt{margin-top:12px}.card{padding:12px}}"
        "@media print{body{margin:0}pre,svg{break-inside:avoid}}</style>"
        "<body>" + "".join(sections) + "</body></html>"
    )


def save_blueprint(blueprint, destination):
    blueprint = normalized_document(blueprint)
    path = Path(destination)
    if path.suffix.lower() != ".json":
        raise ValueError("Save blueprints as .json files.")
    if path.exists():
        # Only a valid previous blueprint is an eligible overwrite target.
        # This also protects databases, knowledge packs and unrelated user JSON.
        load_blueprint(path)
    data = json.dumps(blueprint, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    if len(data.encode("utf-8")) > 2_000_000:
        raise ValueError("Blueprint exceeds the 2 MB limit.")
    _atomic(path, data)
    return path


def load_blueprint(source):
    from fieldforge.blueprints.engine import _json

    with Path(source).open("rb") as stream:
        raw = stream.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Blueprint exceeds the 2 MB limit.")
    try:
        value = _json(raw.decode("utf-8"))
        return normalized_document(value)
    except (KeyError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("Malformed blueprint document.") from exc


def _atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, prefix=".blueprint-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def export_blueprint(blueprint, destination):
    """Create a new directory: prevent overwriting existing projects or a live DB."""
    validate_document(blueprint)
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=False)
    try:
        save_blueprint(blueprint, target / "blueprint.json")
        _atomic(target / "report.html", report_html(blueprint))
        for filename, content in drawings(blueprint).items():
            _atomic(target / filename, content)
        _atomic(target / "README.txt",
                "Open report.html in a browser; all content and drawings work offline.\n"
                "blueprint.json is the editable canonical design; SVG files are vector drawings.\n"
                "After editing JSON, use the studio's Apply edits command to revalidate/recompute.\n"
                "These files contain the project brief and selected source excerpts.\n")
    except Exception as exc:
        # Never recursively remove a user-selected directory on failure.
        # A partial export is visibly incomplete and can be inspected/recovered.
        raise OSError(f"Export incomplete in {target}; choose a new folder to retry.") from exc
    return target
