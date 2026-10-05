"""Build the preparation desk as one local-file HTML document, without dependencies.

The small bundler intentionally accepts only this desk's named imports and named
function/constant exports. It fails on new module syntax rather than silently
shipping unresolved dependencies. This is not a general JavaScript bundler.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import re
from pathlib import Path
from build_mbtiles_worker import insert_mbtiles_worker

FILENAME = "fieldforge-offline.html"
MODULES = ("desk-core.mjs", "places-core.mjs", "field-sheet-core.mjs", "field-sheet.mjs", "places.mjs", "image-core.mjs", "image-viewer.mjs", "route-explorer.mjs", "vector-core.mjs", "vector-viewer.mjs", "mbtiles-core.mjs", "mbtiles-client.mjs", "mvt-renderer.mjs", "mbtiles-coverage.mjs", "mbtiles-route-core.mjs", "mbtiles-route.mjs", "mbtiles-viewer.mjs", "desk.mjs", "offline.mjs")
STYLES = ("desk.css", "route-explorer.css", "image-viewer.css", "places.css", "vector-viewer.css", "mbtiles-viewer.css", "offline.css")


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"Offline desk anchor changed: {old[:80]}")
    return text.replace(old, new, 1)


def bundle_modules(assets: Path) -> str:
    known: dict[str, set[str]] = {}
    parts = []
    for filename in MODULES:
        source = (assets / filename).read_text(encoding="utf-8")
        exports = re.findall(r"^export (?:const|function) ([A-Za-z_$][\w$]*)\b", source, re.M)
        if len(exports) != len(set(exports)):
            raise ValueError(f"Duplicate export in {filename}")
        source = re.sub(r"^export (?=(?:const|function) )", "", source, flags=re.M)

        def resolve(match: re.Match) -> str:
            names, dependency = match.groups()
            names = [name.strip() for name in names.split(",")]
            if dependency not in known or not all(re.fullmatch(r"[A-Za-z_$][\w$]*", name) and name in known[dependency] for name in names):
                raise ValueError(f"Unsupported or unresolved import in {filename}: {match.group(0)}")
            return "const {" + ", ".join(names) + "} = modules[" + json.dumps(dependency) + "];"

        source = re.sub(r'^import \{([^}\n]+)\} from "(\./[^"\n]+)";\s*$', resolve, source, flags=re.M)
        if re.search(r"^\s*(?:import|export)\b|\bimport\s*\(", source, re.M):
            raise ValueError(f"Unsupported module syntax in {filename}; update the offline build")
        if re.search(r"\b(?:fetch|XMLHttpRequest|WebSocket|sendBeacon|importScripts)\s*\(", source):
            raise ValueError(f"Unexpected network API in offline module {filename}")
        key = "./" + filename
        parts.append(f"modules[{json.dumps(key)}] = (() => {{\n{source}\nreturn {{{', '.join(exports)}}};\n}})();")
        known[key] = set(exports)
    script = '''(() => {
"use strict";
try {
const modules = Object.create(null);
''' + "\n".join(parts) + '''
document.getElementById("offlineTools").disabled = false;
document.getElementById("offlineReady").textContent = "Ready on this device. Your files stay in this tab unless you save an export.";
} catch (error) {
document.getElementById("offlineReady").textContent = "The tools could not start in this browser. Reopen the complete downloaded HTML file in a current desktop browser, or use the online portal.";
}
})();'''
    # Prevent a literal script end tag in trusted source strings/comments from
    # terminating the enclosing HTML element. Hash the final emitted bytes.
    return re.sub(r"</script", r"<\/script", script, flags=re.I)


def export_offline(assets: Path, output: Path, original_portal: str, revision: str, favicon: str) -> dict:
    css_match = re.search(r"<style>(.*?)</style>", original_portal, flags=re.S)
    source_match = re.search(r'<ul id="usSourceLinks">.*?</ul>', original_portal, flags=re.S)
    if not css_match or not source_match:
        raise ValueError("Missing source styles or region directory for offline edition")
    catalog = source_match.group(0)
    if len(re.findall(r"<li>", catalog)) != 53:
        raise ValueError("Regional directory changed; review offline planner limits")
    # The shared planner reads these addresses as data, not active links. The
    # offline edition offers the online portal for provider downloads instead.
    catalog = catalog.replace('<ul id="usSourceLinks">', '<ul id="usSourceLinks" hidden>')
    catalog = re.sub(r'\bhref="([^"]+)"', r'data-source-url="\1"', catalog)
    catalog = re.sub(r' (?:target|rel)="[^"]*"| download(?=[ >])', "", catalog)
    desk = (assets / "desk.html").read_text(encoding="utf-8")
    desk = replace_once(desk, '<p class="eyebrow">FieldForge / preparation desk</p>', '<p class="eyebrow">FieldForge / offline edition</p>')
    desk = replace_once(desk, 'Less time online.<br>More prepared offline.', 'Your preparation desk.<br>Ready to travel.')
    desk = replace_once(desk, '<a class="desk-commons" href="commons.html">Explore Commons <span>Chat &amp; owner screen gallery</span></a>', '<a class="desk-commons" href="#offlineHelp">Using your offline copy <span>How to reopen, save and update</span></a>')
    desk = replace_once(desk, '<a class="desk-offline" href="fieldforge-offline.html" download="FieldForge-Offline-Desk.html">Download offline tools <span>One HTML file · no installation</span></a>', '')
    desk = replace_once(desk, '<a href="#libraryTitle">07 <span>Knowledge library</span></a>', '<a href="#offlineHelp">07 <span>Save &amp; reopen</span></a>')
    desk = replace_once(desk, '<a href="#mapAcquisitionTitle">Worldwide, MBTiles &amp; imagery sources</a>', '<a href="#offlineConnection">Use the online portal for map downloads</a>')
    desk = replace_once(desk, '<label class="remember-plan">', '<label class="remember-plan" hidden>')
    desk = replace_once(desk, '<input id="deskRemember" type="checkbox">', '<input id="deskRemember" type="checkbox" disabled>')
    desk = replace_once(desk, 'Selections stay in this tab unless you save them.', 'Save a source plan file to keep your selection; this offline edition does not use browser storage.')
    desk = replace_once(desk, '<a href="commons.html#owner">Owner progress</a><a href="#mapsTitle">Map catalog status</a>', '<a href="#offlineConnection">Online portal</a><a href="#offlineHelp">Save your work</a>')
    desk = insert_mbtiles_worker(desk, assets)
    style = css_match.group(1) + "\n" + "\n".join((assets / name).read_text(encoding="utf-8") for name in STYLES)
    script = bundle_modules(assets)
    shell = (assets / "offline-shell.html").read_text(encoding="utf-8")
    for marker, value in [("<!--DESK-->", desk), ("<!--CATALOG-->", catalog)]:
        shell = replace_once(shell, marker, value)
    fingerprint = hashlib.sha256((shell + style + script).encode()).hexdigest()[:12]
    shell = replace_once(shell, "OFFLINE_EDITION_ID", fingerprint)
    digest = lambda value: base64.b64encode(hashlib.sha256(value.encode("utf-8")).digest()).decode("ascii")
    policy = f"default-src 'none'; script-src 'sha256-{digest(script)}'; style-src 'sha256-{digest(style)}'; img-src data: blob:; connect-src 'none'; worker-src blob:; object-src 'none'; base-uri 'none'; form-action 'none'"
    document = f'''<!doctype html>
<html lang="en" data-edition="offline" data-sources-enabled="false"><head>
<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="{html.escape(policy, quote=True)}">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer">
<title>FieldForge · Offline preparation desk</title>
<meta name="description" content="A standalone offline source planner, GPX inspector, local map-image viewer and saved places.">
{favicon}<style>{style}</style></head><body>{shell}<script>{script}</script></body></html>
'''
    data = document.encode("utf-8")
    output.mkdir(parents=True, exist_ok=True)
    (output / FILENAME).write_bytes(data)
    metadata = {"kind":"fieldforge-offline-tools", "schema_version":1, "filename":FILENAME, "bytes":len(data), "sha256":hashlib.sha256(data).hexdigest(), "edition_id":fingerprint, "portal_snapshot":revision, "contains_user_data":False, "includes_map_datasets":False}
    (output / "offline-download.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata
