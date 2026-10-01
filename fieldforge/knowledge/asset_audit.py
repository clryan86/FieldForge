"""Read-only verification of local FieldForge assets against an explicit manifest.

Standard-library-only; runnable directly or with ``python -m``. Snapshot records
current bytes, not trusted provenance. Neither command downloads or opens media.
Use a stable, trusted local filesystem: this is not a hostile-filesystem sandbox.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
import stat
import sys
import tempfile
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SCHEMA = "fieldforge.offline-assets"
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_ASSETS = 10_000
MAX_TREE_ENTRIES = 50_000
DEFAULT_FILE_BUDGET = 2 * 1024**3
DEFAULT_TOTAL_BUDGET = 8 * 1024**3
CHUNK_BYTES = 1024 * 1024
KINDS = frozenset({"text", "pdf", "audio", "video", "image", "game", "data", "other"})
STATES = ("verified", "missing", "changed", "unsafe", "unreadable", "not_checked")
TEXT_FIELDS = {"asset_id": 200, "title": 500, "path": 1024, "kind": 20,
               "collection": 200, "source_url": 2048, "license": 1000,
               "review_status": 20, "sha256": 64}
LIMITATIONS = (
    "Verified means bytes match this manifest, not that a publisher is authentic.",
    "A snapshot records current bytes; it cannot establish that those bytes were correct before it ran.",
    "Rights and review labels are supplied metadata, not permission or independent expert review.",
    "A present PDF, game, audio, or video file is not proof that a device can open or play it.",
    "No file is executed, unpacked, repaired, deleted, or downloaded by this check.",
    "Only listed assets are verified. Extra files are not checked; counts do not measure completeness.",
    "Reports include relative filenames and descriptive metadata, but not file contents or the root path.",
    "Use a stable, trusted local filesystem. Checks detect common races, not hostile filesystem attacks.",
)
_REASONS = {
    "verified": "Size and SHA-256 match the manifest.",
    "missing": "The listed file or a parent directory is missing.",
    "changed_size": "File size does not match the manifest.",
    "changed_hash": "SHA-256 does not match the manifest.",
    "unsafe": "A path component is a link, reparse point, or unsupported file type.",
    "unreadable": "The file could not be read. Check permissions and the storage device.",
    "not_checked": "The file exceeds the per-file or remaining total hashing budget.",
    "unstable": "The file changed during verification. Retry on a stable copy.",
}
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?\Z", re.I)
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class AssetInputError(ValueError):
    """Invalid input; messages deliberately omit input text and absolute paths."""


class _FileProblem(Exception):
    def __init__(self, status: str, reason: str, read: int = 0,
                 observed_bytes: int | None = None):
        super().__init__(_REASONS[reason])
        self.status, self.reason = status, reason
        self.read, self.observed_bytes = read, observed_bytes


@dataclass(frozen=True)
class AssetSpec:
    asset_id: str
    title: str
    path: str
    kind: str
    collection: str
    bytes: int
    sha256: str
    source_url: str
    license: str
    review_status: str


@dataclass(frozen=True)
class AssetResult:
    asset: AssetSpec
    status: str
    reason: str
    observed_bytes: int | None
    observed_sha256: str
    bytes_read: int
    metadata_gaps: tuple[str, ...]


@dataclass(frozen=True)
class AssetReport:
    schema: str
    version: int
    manifest_sha256: str
    status: str
    counts: dict[str, int]
    collections: dict[str, dict[str, int]]
    assets: tuple[AssetResult, ...]
    limitations: tuple[str, ...] = LIMITATIONS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def exit_code(self) -> int:
        return {"verified": 0, "attention_required": 1,
                "incomplete": 2, "integrity_failed": 2}[self.status]


def _integer(value: object, maximum: int = 2**63 - 1) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _text(value: object, limit: int, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise AssetInputError("Invalid or oversized metadata text.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise AssetInputError("Invalid Unicode metadata.") from exc
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value):
        raise AssetInputError("Control or invisible formatting characters are not permitted.")
    if required and not value.strip():
        raise AssetInputError("Required metadata is empty.")
    return value


def _relative_path(value: str) -> str:
    _text(value, 1024, True)
    parts = value.split("/")
    if len(parts) > 64 or any(
        part in {"", ".", ".."} or part != part.strip()
        or part.endswith(".") or len(part.encode("utf-8")) > 255
        or _RESERVED.fullmatch(part) or any(c in part for c in '\\:*?"<>|')
        for part in parts
    ):
        raise AssetInputError("Asset paths must be portable relative paths without traversal.")
    return value


def _portable_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise AssetInputError("Duplicate JSON keys are not permitted.")
        out[key] = value
    return out


def _nonfinite(_value: str) -> None:
    raise AssetInputError("Non-finite JSON numbers are not permitted.")


def parse_manifest(raw: bytes) -> tuple[AssetSpec, ...]:
    """Validate a bounded manifest completely before touching any listed asset."""
    if not isinstance(raw, bytes) or len(raw) > MAX_MANIFEST_BYTES:
        raise AssetInputError("Manifest is not bytes or exceeds its size limit.")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                              parse_constant=_nonfinite)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise AssetInputError("Manifest is not valid bounded UTF-8 JSON.") from exc
    if not isinstance(document, dict) or set(document) != {"schema", "version", "assets"}:
        raise AssetInputError("Manifest fields do not match the asset schema.")
    if document["schema"] != SCHEMA or type(document["version"]) is not int \
            or document["version"] != 1:
        raise AssetInputError("Unsupported asset manifest schema or version.")
    rows = document["assets"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ASSETS:
        raise AssetInputError("Manifest must contain between 1 and 10,000 assets.")
    assets: list[AssetSpec] = []
    ids: set[str] = set()
    paths: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(TEXT_FIELDS) | {"bytes"}:
            raise AssetInputError("Asset fields do not match the schema.")
        for key, limit in TEXT_FIELDS.items():
            _text(row[key], limit, key not in {"source_url", "license"})
        _relative_path(row["path"])
        if row["asset_id"] != row["asset_id"].strip():
            raise AssetInputError("Asset identifiers may not have surrounding whitespace.")
        if not _integer(row["bytes"]) or not _SHA.fullmatch(row["sha256"]):
            raise AssetInputError("Asset size or SHA-256 is invalid.")
        if row["kind"] not in KINDS or row["review_status"] not in {
            "unreviewed", "reviewed", "outdated"
        }:
            raise AssetInputError("Unsupported asset kind or review status.")
        if row["source_url"]:
            try:
                url = urlsplit(row["source_url"])
                valid = url.scheme in {"http", "https"} and bool(url.hostname) \
                    and url.username is None and url.password is None
                _ = url.port
            except ValueError as exc:
                raise AssetInputError("Invalid source URL.") from exc
            if not valid or any(c.isspace() for c in row["source_url"]):
                raise AssetInputError("Source URLs must be HTTP(S) URLs without credentials.")
        id_key, path_key = _portable_key(row["asset_id"]), _portable_key(row["path"])
        if id_key in ids or path_key in paths:
            raise AssetInputError("Duplicate or portability-colliding asset IDs or paths.")
        ids.add(id_key)
        paths.add(path_key)
        assets.append(AssetSpec(**row))
    # A listed file cannot also be a parent of another listed file.
    for asset in assets:
        components = asset.path.split("/")
        if any(_portable_key("/".join(components[:n])) in paths
               for n in range(1, len(components))):
            raise AssetInputError("A listed asset conflicts with a required directory.")
    return tuple(assets)


def _root(path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_dir():
            raise AssetInputError("Asset root must be an existing directory.")
        return resolved
    except (OSError, RuntimeError) as exc:
        raise AssetInputError("Asset root is not accessible.") from exc


def _linked(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400  # Windows reparse point
    )


def _safe_path(root: Path, relative: str) -> tuple[Path, os.stat_result]:
    _relative_path(relative)
    current = root
    parts = relative.split("/")
    for index, part in enumerate(parts):
        current = current / part
        info = current.lstat()
        wanted = stat.S_ISREG if index == len(parts) - 1 else stat.S_ISDIR
        if _linked(info) or not wanted(info.st_mode):
            raise _FileProblem("unsafe", "unsafe")
    return current, info


def _fingerprint(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _hash_file(root: Path, relative: str, expected_bytes: int | None,
               file_budget: int, remaining: int) -> tuple[str, int, int]:
    read = 0
    size: int | None = None
    descriptor = -1
    try:
        path, before = _safe_path(root, relative)
        size = before.st_size
        if expected_bytes is not None and size != expected_bytes:
            raise _FileProblem("changed", "changed_size", observed_bytes=size)
        if size > min(file_budget, remaining):
            raise _FileProblem("not_checked", "not_checked", observed_bytes=size)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if _linked(opened) or not stat.S_ISREG(opened.st_mode) \
                or _fingerprint(before) != _fingerprint(opened):
            raise _FileProblem("unreadable", "unstable", read, size)
        digest = hashlib.sha256()
        while read < size:
            block = os.read(descriptor, min(CHUNK_BYTES, size - read))
            if not block:
                raise _FileProblem("unreadable", "unstable", read, size)
            read += len(block)
            digest.update(block)
        after = os.fstat(descriptor)
        _, current = _safe_path(root, relative)
        if _fingerprint(opened) != _fingerprint(after) \
                or _fingerprint(opened) != _fingerprint(current):
            raise _FileProblem("unreadable", "unstable", read, size)
        return digest.hexdigest(), size, read
    except _FileProblem as exc:
        # Preserve consumed budget when a path becomes unsafe after the read.
        exc.read = max(exc.read, read)
        raise
    except FileNotFoundError as exc:
        raise _FileProblem("missing" if not read else "unreadable",
                           "missing" if not read else "unstable", read, size) from exc
    except OSError as exc:
        raise _FileProblem("unreadable", "unreadable", read, size) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _budgets(file_budget: int, total_budget: int) -> None:
    if not _integer(file_budget) or not _integer(total_budget):
        raise AssetInputError("Hash budgets must be nonnegative 64-bit integer byte counts.")


def _metadata_gaps(asset: AssetSpec) -> tuple[str, ...]:
    gaps = []
    if not asset.source_url.strip():
        gaps.append("Source URL not recorded")
    if not asset.license.strip():
        gaps.append("Rights statement not recorded")
    if asset.review_status != "reviewed":
        gaps.append("Review status: " + asset.review_status)
    return tuple(gaps)


def audit_assets(root: Path, manifest: bytes, *, file_budget: int = DEFAULT_FILE_BUDGET,
                 total_budget: int = DEFAULT_TOTAL_BUDGET) -> AssetReport:
    """Hash only validated listed files. Never write to the library or follow links."""
    assets = parse_manifest(manifest)
    _budgets(file_budget, total_budget)
    root = _root(Path(root))
    results: list[AssetResult] = []
    remaining = total_budget
    for asset in assets:
        try:
            actual_hash, actual_size, consumed = _hash_file(
                root, asset.path, asset.bytes, file_budget, remaining
            )
            matched = actual_hash == asset.sha256
            result = AssetResult(asset, "verified" if matched else "changed",
                                 "verified" if matched else "changed_hash",
                                 actual_size, actual_hash, consumed, _metadata_gaps(asset))
        except _FileProblem as exc:
            result = AssetResult(asset, exc.status, exc.reason, exc.observed_bytes,
                                 "", exc.read, _metadata_gaps(asset))
        remaining -= result.bytes_read
        results.append(result)
    counts: dict[str, int] = {key: 0 for key in STATES}
    counts.update(Counter(result.status for result in results))
    counts.update(total=len(results), hashed_bytes=total_budget - remaining,
                  verified_bytes=sum(r.asset.bytes for r in results if r.status == "verified"),
                  expected_bytes=sum(a.bytes for a in assets),
                  metadata_gaps=sum(bool(r.metadata_gaps) for r in results))
    if any(counts[key] for key in ("missing", "changed", "unsafe", "unreadable")):
        status = "integrity_failed"
    elif counts["not_checked"]:
        status = "incomplete"
    elif counts["metadata_gaps"]:
        status = "attention_required"
    else:
        status = "verified"
    groups: dict[str, dict[str, int]] = {}
    for result in results:
        name = result.asset.collection
        if name not in groups:
            groups[name] = {key: 0 for key in STATES}
            groups[name].update(total=0, verified_bytes=0)
        group = groups[name]
        group["total"] += 1
        group[result.status] += 1
        if result.status == "verified":
            group["verified_bytes"] += result.asset.bytes
    collections = dict(sorted(groups.items()))
    return AssetReport(SCHEMA + ".report", 1, hashlib.sha256(manifest).hexdigest(),
                       status, counts, collections, tuple(results))


def _guess_kind(path: str) -> str:
    extension = Path(path).suffix.lower()
    for kind, extensions in {
        "text": {".txt", ".md", ".html", ".epub"}, "pdf": {".pdf"},
        "audio": {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".mid"},
        "video": {".mp4", ".webm", ".mkv", ".mov"},
        "image": {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"},
        "data": {".json", ".csv", ".sqlite", ".db", ".mbtiles", ".zim"},
    }.items():
        if extension in extensions:
            return kind
    return "other"


def snapshot_assets(root: Path, *, file_budget: int = DEFAULT_FILE_BUDGET,
                    total_budget: int = DEFAULT_TOTAL_BUDGET) -> bytes:
    """Make an unsigned baseline of ALL regular files below a selected directory.

    Reject links, inaccessible entries, oversize scans, and empty roots instead of
    silently creating a partial inventory. Metadata starts explicitly unreviewed.
    """
    _budgets(file_budget, total_budget)
    root = _root(Path(root))
    paths: list[str] = []
    pending = [root]
    examined = 0
    while pending:
        folder = pending.pop()
        try:
            # Never follow a discovered directory link, including replacement races.
            if folder != root:
                relative_folder = folder.relative_to(root).as_posix()
                parent = root
                for part in relative_folder.split("/"):
                    parent /= part
                    info = parent.lstat()
                    if _linked(info) or not stat.S_ISDIR(info.st_mode):
                        raise AssetInputError("Snapshot contains an unsafe directory.")
            with os.scandir(folder) as entries:
                for entry in entries:
                    examined += 1
                    if examined > MAX_TREE_ENTRIES:
                        raise AssetInputError("Snapshot exceeds its directory-entry limit.")
                    info = entry.stat(follow_symlinks=False)
                    relative = Path(entry.path).relative_to(root).as_posix()
                    _relative_path(relative)
                    if _linked(info):
                        raise AssetInputError("Snapshot refuses symbolic links and reparse points.")
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(Path(entry.path))
                    elif stat.S_ISREG(info.st_mode):
                        paths.append(relative)
                        if len(paths) > MAX_ASSETS:
                            raise AssetInputError("Snapshot exceeds its asset-count limit.")
                    else:
                        raise AssetInputError("Snapshot only supports regular files and directories.")
        except OSError as exc:
            raise AssetInputError("Snapshot directory could not be read.") from exc
    assets = []
    remaining = total_budget
    for relative in sorted(paths):
        try:
            digest, size, consumed = _hash_file(root, relative, None, file_budget, remaining)
        except _FileProblem as exc:
            raise AssetInputError("Snapshot stopped: " + _REASONS[exc.reason]) from exc
        remaining -= consumed
        parts = relative.split("/")
        assets.append(asdict(AssetSpec(
            "asset-" + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24],
            Path(relative).name, relative, _guess_kind(relative),
            parts[0] if len(parts) > 1 else "Unsorted", size, digest, "", "", "unreviewed"
        )))
    result = _json_bytes({"schema": SCHEMA, "version": 1, "assets": assets})
    parse_manifest(result)
    return result


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


_REPORT_SCRIPT = """const search = document.getElementById('search');
const statusFilter = document.getElementById('status-filter');
const rows = Array.from(document.querySelectorAll('tbody tr'));
function filterRows() {
  const query = search.value.toLocaleLowerCase().trim();
  let visible = 0;
  for (const row of rows) {
    const match = (!statusFilter.value || row.dataset.status === statusFilter.value)
      && row.textContent.toLocaleLowerCase().includes(query);
    row.hidden = !match;
    if (match) visible++;
  }
  document.getElementById('shown').textContent = visible + ' of ' + rows.length + ' assets shown';
}
search.addEventListener('input', filterRows);
statusFilter.addEventListener('change', filterRows);
filterRows();"""


def render_html(report: AssetReport) -> str:
    """An escaped, self-contained report; no external scripts, fonts, or media."""
    escape = html.escape
    rows = []
    for result in report.assets:
        asset = result.asset
        gaps = "; ".join(result.metadata_gaps) or "No metadata gaps flagged"
        rows.append(
            f'<tr data-status="{escape(result.status)}"><td data-label="Asset"><strong>{escape(asset.title)}</strong>'
            f'<br><code>{escape(asset.path)}</code><br><small>{escape(asset.asset_id)}</small></td>'
            f'<td data-label="Collection">{escape(asset.collection)}<br><small>{escape(asset.kind)}</small></td>'
            f'<td data-label="Verification"><strong>{escape(result.status.replace("_", " "))}</strong>'
            f'<br>{escape(_REASONS[result.reason])}</td>'
            f'<td data-label="Expected bytes">{asset.bytes:,}<br><small>Read: {result.bytes_read:,}</small></td>'
            f'<td data-label="Metadata">{escape(gaps)}<details><summary>Recorded metadata</summary>'
            f'<p>Source: {escape(asset.source_url or "Not recorded")}</p>'
            f'<p>Rights: {escape(asset.license or "Not recorded")}</p>'
            f'<p>Review: {escape(asset.review_status)}</p>'
            f'<p>Expected SHA-256: <code>{asset.sha256}</code></p>'
            f'<p>Observed SHA-256: <code>{result.observed_sha256 or "Not computed"}</code></p>'
            '</details></td></tr>'
        )
    cards = "".join(f'<div class="card"><span>{key.replace("_", " ")}</span>'
                    f'<strong>{report.counts[key]:,}</strong></div>' for key in STATES)
    options = "".join(f'<option value="{key}">{key.replace("_", " ").title()}</option>'
                      for key in STATES)
    collection_text = "".join(
        f'<li><strong>{escape(name)}</strong>: {values["verified"]} of '
        f'{values["total"]} listed assets verified.</li>'
        for name, values in report.collections.items()
    )
    limits = "".join(f'<li>{escape(item)}</li>' for item in report.limitations)
    script_hash = base64.b64encode(hashlib.sha256(_REPORT_SCRIPT.encode()).digest()).decode()
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-{script_hash}'">
<title>FieldForge | Offline asset verification</title>
<style>
:root{{color-scheme:dark; font-family:system-ui,sans-serif; background:#101820;color:#e8eef2}}
*{{box-sizing:border-box}}body{{max-width:1300px;margin:auto;padding:24px}}
h1{{font-size:clamp(1.8rem,5vw,2.7rem);margin:.4em 0}}p,li{{line-height:1.6}}
header>p{{max-width:80ch;color:#c4d1da}}.eyebrow{{letter-spacing:.13em;font-size:.8rem}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin:24px 0}}
.card{{background:#1b2a35;border:1px solid #385160;border-radius:10px;padding:16px}}
.card span{{display:block;text-transform:capitalize}}.card strong{{font-size:2rem;display:block;margin-top:8px}}
.controls{{display:flex;gap:16px;flex-wrap:wrap;margin:24px 0}}label{{display:grid;gap:8px;flex:1;min-width:180px}}
input,select{{font:inherit;padding:12px;border:1px solid #7d98aa;border-radius:5px;background:#162530;color:inherit;width:100%}}
:focus-visible{{outline:3px solid #e6bf73;outline-offset:3px}}.table-wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:.92rem}}th,td{{text-align:left;padding:14px 10px;vertical-align:top;border-bottom:1px solid #385160;overflow-wrap:anywhere}}
th{{background:#1b2a35}}th:first-child{{width:26%}}th:nth-child(2){{width:15%}}th:nth-child(3){{width:25%}}th:nth-child(4){{width:12%}}th:last-child{{width:22%}}
code{{overflow-wrap:anywhere;word-break:break-word}}small{{color:#becdd7}}summary{{cursor:pointer;padding:8px 0}}
.notice{{border-left:4px solid #e6bf73;padding:12px 18px;background:#1b2a35}}
[hidden]{{display:none!important}}footer{{margin-top:28px;border-top:1px solid #385160;padding-top:18px}}
@media(max-width:600px){{body{{padding:16px}}.controls{{display:block}}label{{margin:12px 0}}
.table-wrap{{overflow:visible}}table,tbody,caption{{display:block;width:100%}}thead{{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}}
tr{{display:block;background:#1b2a35;border:1px solid #385160;border-radius:8px;margin:16px 0;padding:10px}}td{{display:block;width:100%;border:0;padding:8px}}
td::before{{content:attr(data-label);display:block;font-size:.76rem;text-transform:uppercase;letter-spacing:.08em;color:#becdd7;margin-bottom:5px}}}}
@media print{{:root{{color-scheme:light;background:white;color:black}}.controls{{display:none}}body{{max-width:none;padding:0}}.table-wrap{{overflow:visible}}table{{min-width:0}}.card,th,.notice{{background:white;color:black}}}}
</style></head><body>
<header><p class="eyebrow">FIELD FORGE / LIBRARY HEALTH</p><h1>Are the files really here?</h1>
<p>Offline asset verification checks listed local files against a manifest. Matching bytes are not a guarantee of accurate advice, reuse permission, or playable media.</p></header>
<p class="notice"><strong>Result: {escape(report.status.replace("_", " "))}.</strong>
{report.counts["verified"]:,} of {report.counts["total"]:,} listed files verified.
{report.counts["metadata_gaps"]:,} files have metadata gaps. Hashed {report.counts["hashed_bytes"]:,} bytes.</p>
<section class="cards" aria-label="Verification counts">{cards}</section>
<details><summary>Collections and scope</summary><ul>{collection_text}</ul><ul>{limits}</ul></details>
<div class="controls"><label for="search">Search listed assets<input id="search" type="search" placeholder="Title, collection, or relative filename"></label>
<label for="status-filter">Verification status<select id="status-filter"><option value="">All statuses</option>{options}</select></label></div>
<p id="shown" role="status" aria-live="polite">{report.counts["total"]} assets shown</p>
<div class="table-wrap" role="region" aria-label="Asset verification results" tabindex="0">
<table><caption>Listed offline assets</caption><thead><tr><th scope="col">Asset</th><th scope="col">Collection</th><th scope="col">Verification</th><th scope="col">Expected bytes</th><th scope="col">Metadata</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<footer><p>Manifest SHA-256: <code>{report.manifest_sha256}</code></p><p>This is a point-in-time check, not a promise of future availability. No network connection is needed to use this report. Review relative filenames before sharing it.</p></footer>
<script>{_REPORT_SCRIPT}</script></body></html>'''


def _read_manifest(path: Path) -> bytes:
    descriptor = -1
    try:
        before = path.lstat()
        if _linked(before) or not stat.S_ISREG(before.st_mode) \
                or before.st_size > MAX_MANIFEST_BYTES:
            raise AssetInputError("Manifest must be a bounded regular file, not a link.")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if _fingerprint(before) != _fingerprint(opened):
            raise AssetInputError("Manifest changed while opening.")
        chunks = []
        remaining = MAX_MANIFEST_BYTES + 1
        while remaining:
            block = os.read(descriptor, min(CHUNK_BYTES, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        raw = b"".join(chunks)
        if len(raw) > MAX_MANIFEST_BYTES or _fingerprint(opened) != _fingerprint(os.fstat(descriptor)) \
                or _fingerprint(opened) != _fingerprint(path.lstat()):
            raise AssetInputError("Manifest changed or exceeded its size limit.")
        return raw
    except OSError as exc:
        raise AssetInputError("Manifest cannot be read.") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _outside_root(path: Path, root: Path) -> None:
    try:
        destination = path.resolve()
        if destination == root or root in destination.parents:
            raise AssetInputError("Outputs must be outside the asset directory.")
    except (OSError, RuntimeError) as exc:
        raise AssetInputError("Output path cannot be resolved.") from exc


def write_new(path: Path, content: bytes) -> None:
    """Publish one complete report without replacing any existing destination.

    Uses a same-directory hard link for exclusive publication. Fail closed on
    filesystems without hard-link support; never fall back to overwriting files.
    """
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".fieldforge-", dir=path.parent,
                                         delete=False) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    except FileExistsError as exc:
        raise AssetInputError("Output already exists; choose a new filename.") from exc
    except OSError as exc:
        raise AssetInputError("Output could not be published; a writable hard-link-capable directory is required.") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, description in (("snapshot", "Record current bytes; not a trusted-source certificate"),
                              ("verify", "Verify only assets listed in a manifest")):
        command = commands.add_parser(name, help=description)
        command.add_argument("root", type=Path, help="Selected local asset directory")
        if name == "verify":
            command.add_argument("manifest", type=Path)
            command.add_argument("--format", choices=("json", "html"), default="html")
        command.add_argument("--output", type=Path, required=True,
                             help="New output file OUTSIDE the asset directory; never overwritten")
        command.add_argument("--max-file-bytes", type=int, default=DEFAULT_FILE_BUDGET)
        command.add_argument("--max-total-bytes", type=int, default=DEFAULT_TOTAL_BUDGET)
    args = parser.parse_args(argv)
    try:
        root = _root(args.root)
        _outside_root(args.output, root)
        if args.output.exists() or args.output.is_symlink():
            raise AssetInputError("Output already exists; choose a new filename.")
        budgets = {"file_budget": args.max_file_bytes, "total_budget": args.max_total_bytes}
        if args.command == "snapshot":
            result = snapshot_assets(root, **budgets)
            write_new(args.output, result)
            print("Snapshot saved. Current bytes recorded; provenance, rights, and expert review are not established.")
            return 0
        report = audit_assets(root, _read_manifest(args.manifest), **budgets)
        output = render_html(report).encode("utf-8") if args.format == "html" \
            else _json_bytes(report.to_dict())
        write_new(args.output, output)
        print(f'{report.status}: {report.counts["verified"]}/{report.counts["total"]} '
              f'verified; {report.counts["not_checked"]} not checked. Report saved.')
        return report.exit_code
    except (AssetInputError, OSError, RecursionError) as exc:
        message = str(exc) if isinstance(exc, AssetInputError) else "Filesystem operation failed."
        print("Asset check: " + message, file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("Asset check interrupted; a partial verification is not a successful check.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
