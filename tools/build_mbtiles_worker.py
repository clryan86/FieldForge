"""Bundle the pinned local SQLite reader into an inert, self-contained payload."""
import base64
import hashlib
import html
import json
import re
from pathlib import Path


def worker_source(assets: Path) -> str:
    vendor = assets / "vendor"
    provenance = json.loads((vendor / "sql.js-provenance.json").read_text())
    raw = (vendor / "sql-asm-1.14.2.js").read_bytes()
    if hashlib.sha256(raw).hexdigest() != provenance["sha256"]:
        raise ValueError("Pinned SQLite reader checksum differs; review the dependency update")
    wasm_assets = {}
    for key, filename in (
        ("wasm_loader", "sql-wasm-1.14.2.js"),
        ("wasm_binary", "sql-wasm-1.14.2.wasm"),
    ):
        receipt = provenance[key]
        data = (vendor / filename).read_bytes()
        if receipt["file"] != filename or hashlib.sha256(data).hexdigest() != receipt["sha256"]:
            raise ValueError("Pinned SQLite WebAssembly checksum differs; review the dependency update")
        wasm_assets[key] = data
    core = "\n".join((assets / name).read_text() for name in ("mbtiles-core.mjs", "mvt-core.mjs"))
    core = re.sub(r"^export (?=(?:const|function) )", "", core, flags=re.M)
    if re.search(r"^\s*(?:export|import)\b", core, re.M):
        raise ValueError("Unsupported worker core module syntax")
    # Both upstream factories stay scoped. The entire WASM binary is embedded;
    # initialization never needs a URL, importScripts or a companion file.
    factories = (
        "const mbInitAsm = (() => {\n" + raw.decode() + "\nreturn initSqlJs;\n})();\n"
        + "const mbInitWasm = (() => {\n" + wasm_assets["wasm_loader"].decode()
        + "\nreturn initSqlJs;\n})();\n"
        + "const mbWasmBase64 = "
        + json.dumps(base64.b64encode(wasm_assets["wasm_binary"]).decode()) + ";\n"
    )
    return factories + core + "\n" + (assets / "mbtiles-worker.js").read_text()


def insert_mbtiles_worker(document: str, assets: Path) -> str:
    marker = "<!--MBTILES_WORKER-->"
    if document.count(marker) != 1:
        raise ValueError("Missing or duplicate MBTiles worker placeholder")
    encoded = base64.b64encode(worker_source(assets).encode()).decode()
    license_text = (assets / "vendor/sql.js-LICENSE.txt").read_text()
    payload = f'<div id="mbWorkerPayload" hidden>{encoded}</div><details class="mb-license"><summary>Local SQLite component licence</summary><pre>{html.escape(license_text)}</pre></details>'
    return document.replace(marker, payload, 1)
