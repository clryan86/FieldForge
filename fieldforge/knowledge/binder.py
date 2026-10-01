"""Read-only article snapshots and self-contained, print-friendly HTML binders.

No scripts, external assets, rendered Markdown, automatic browser/printer action,
or stored export history. Export permission and source reliability are not inferred.
"""

from __future__ import annotations

import hashlib
import html
import os
import sqlite3
import time
import webbrowser
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fieldforge.knowledge import KnowledgeArticle, KnowledgeLibrary

MAX_ARTICLES = 50
MAX_TEXT_BYTES = 8 * 1024 * 1024
MAX_HTML_BYTES = 64 * 1024 * 1024
NOTICE = (
    "A captured reference collection, not a complete curriculum or emergency service. "
    "Source, review, safety and rights fields are author-supplied, not independently verified. "
    "A checksum identifies captured text; it does not prove correctness or authorship."
)
PRIVACY = (
    "This readable file is unencrypted. Export only text you have permission to copy. "
    "Article bodies may themselves contain private information. Household, learning and incident "
    "records are not included. Private article notes are excluded unless explicitly selected."
)
_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; color: #172b2b; background: #ecf0ec; font: 17px/1.6 system-ui, sans-serif; }
main { max-width: 900px; margin: 40px auto; background: white; padding: 52px; }
.eyebrow { color: #355c48; font: 700 12px/1.5 system-ui, sans-serif; letter-spacing: .17em; }
h1 { font-size: 40px; line-height: 1.15; margin: 16px 0; overflow-wrap: anywhere; }
h2 { font-size: 26px; line-height: 1.25; overflow-wrap: anywhere; }
h3 { font-size: 16px; }
.notice { padding: 16px 20px; border-left: 4px solid #55785a; background: #f2f5ef; }
.private { border: 2px solid #6e4124; padding: 14px; color: #472918; }
.meta, .instructions { font-size: 14px; color: #3d5149; }
.instructions { border: 1px solid #b9c7bc; padding: 12px 16px; }
nav { margin: 32px 0; }
nav ol { padding-left: 24px; }
nav li { padding: 7px 0; border-bottom: 1px solid #dee5df; }
a { color: #234c37; }
.entry { margin-top: 48px; border-top: 2px solid #385f47; padding-top: 20px; }
dl { display: grid; grid-template-columns: 145px 1fr; font-size: 13px; line-height: 1.5; gap: 7px 16px; }
dt { font-weight: 700; }
dd { margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
.body, .note-body { white-space: pre-wrap; overflow-wrap: anywhere; tab-size: 4; unicode-bidi: plaintext; }
.body { font-family: Georgia, serif; font-size: 18px; line-height: 1.65; }
.note { margin-top: 28px; border: 1px solid #6e4124; padding: 14px; }
.hash { font-family: ui-monospace, monospace; font-size: 11px; }
footer { font-size: 12px; color: #3d5149; margin-top: 32px; }
@media (max-width: 640px) {
 main { margin: 0; padding: 24px; } h1 { font-size: 30px; }
 dl { grid-template-columns: 1fr; gap: 2px; } dd { margin-bottom: 7px; }
}
@media print {
 @page { margin: 18mm; }
 body { background: white; color: black; font-size: 11pt; }
 main { margin: 0; padding: 0; max-width: none; }
 .instructions { display: none; }
 .entry { break-before: page; border-color: black; }
 h1 { font-size: 28pt; } h2 { font-size: 20pt; }
 .body { font-size: 12pt; line-height: 1.5; }
 .notice, .private, .note { background: white; color: black; }
 .meta, footer { color: black; }
 nav li, dt, h2, h3 { break-inside: avoid; }
 h2, h3 { break-after: avoid; }
 p { orphans: 3; widows: 3; }
 a { color: black; text-decoration: none; }
}
"""


@dataclass(frozen=True)
class BinderEntry:
    article: KnowledgeArticle
    note: str | None = None


@dataclass(frozen=True)
class FieldBinder:
    title: str
    captured_at: str
    entries: tuple[BinderEntry, ...]
    include_notes: bool


def _title(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200 or any(ord(c) < 32 for c in value):
        raise ValueError("binder title must contain 1–200 characters without control characters")
    return value.strip()


def capture_binder(database: str | Path, *, slugs: tuple[str, ...] | None = None,
                   bookmarks: bool = False, include_notes: bool = False,
                   title: str = "FieldForge Field Binder") -> FieldBinder:
    """Read one consistent snapshot. Choose explicit IDs OR all library bookmarks.

    Missing/corrupt articles or exceeded limits abort the whole preview. No silent
    truncation; no extra articles are substituted based on titles or search terms.
    """
    title = _title(title)
    if type(bookmarks) is not bool or type(include_notes) is not bool:
        raise ValueError("bookmark and note options must be booleans")
    if bookmarks == (slugs is not None):
        raise ValueError("choose explicit article IDs OR all bookmarked articles")
    if slugs is not None:
        if not isinstance(slugs, tuple) or not 1 <= len(slugs) <= MAX_ARTICLES:
            raise ValueError(f"choose 1–{MAX_ARTICLES} article IDs")
        if any(not isinstance(s, str) or not s or len(s) > 200 or "\x00" in s for s in slugs):
            raise ValueError("invalid article ID")
        if len(set(slugs)) != len(slugs):
            raise ValueError("duplicate article IDs in binder selection")
    path = Path(database).expanduser().resolve()
    deadline = time.monotonic() + 5
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.25)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        try:
            db.execute("BEGIN")
            if bookmarks:
                slugs = tuple(row[0] for row in db.execute(
                    "SELECT a.slug FROM knowledge_articles a JOIN knowledge_annotations n ON n.slug=a.slug "
                    "WHERE n.bookmarked=1 ORDER BY a.title COLLATE NOCASE,a.slug LIMIT ?",
                    (MAX_ARTICLES + 1,),
                ))
                if not slugs:
                    raise ValueError("No bookmarked articles. Bookmark articles in the library first.")
                if len(slugs) > MAX_ARTICLES:
                    raise ValueError(f"More than {MAX_ARTICLES} bookmarks; export a smaller selection instead.")
            entries, budget = [], 0
            for slug in slugs:
                if time.monotonic() > deadline:
                    raise TimeoutError("binder preview timed out; try fewer articles")
                size = db.execute("SELECT length(CAST(body AS BLOB)) FROM knowledge_articles WHERE slug=?", (slug,)).fetchone()
                if size is None:
                    raise ValueError(f"Article no longer installed: {slug}. Refresh before trying again.")
                if type(size[0]) is not int or size[0] > MAX_TEXT_BYTES - budget:
                    raise ValueError("binder exceeds the 8 MiB text limit; select fewer articles")
                row = db.execute("SELECT * FROM knowledge_articles WHERE slug=?", (slug,)).fetchone()
                article = KnowledgeLibrary._article(row)
                if article.checksum != row["checksum"]:
                    raise ValueError(f"Article checksum mismatch: {slug}. No binder was created.")
                budget += size[0]
                note = None
                if include_notes:
                    saved = db.execute("SELECT note FROM knowledge_annotations WHERE slug=?", (slug,)).fetchone()
                    note = saved[0] if saved else ""
                    if not isinstance(note, str) or len(note) > 100_000 or "\x00" in note:
                        raise ValueError("invalid saved article note")
                    budget += len(note.encode("utf-8"))
                if budget > MAX_TEXT_BYTES:
                    raise ValueError("binder exceeds the 8 MiB text limit; select fewer articles")
                entries.append(BinderEntry(article, note))
        finally:
            db.set_progress_handler(None, 0)
    return FieldBinder(title, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       tuple(entries), include_notes)


def render_binder(binder: FieldBinder) -> bytes:
    """Render only escaped text plus fixed HTML/CSS. URLs are inert text, not links."""
    if not isinstance(binder, FieldBinder) or not 1 <= len(binder.entries) <= MAX_ARTICLES:
        raise ValueError("preview a nonempty binder first")
    title = _title(binder.title)
    if type(binder.include_notes) is not bool or not isinstance(binder.captured_at, str):
        raise ValueError("invalid binder snapshot")
    e = html.escape
    policy = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
    out = [f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
           f'<meta http-equiv="Content-Security-Policy" content="{e(policy)}">'
           '<meta name="referrer" content="no-referrer">'
           '<meta name="viewport" content="width=device-width, initial-scale=1">'
           f'<title>{e(title)}</title><style>{_STYLE}</style></head><body><main>',
           '<header><div class="eyebrow">FIELDFORGE / OFFLINE REFERENCE</div>',
           f'<h1>{e(title)}</h1><p class="meta">{len(binder.entries)} complete local articles · '
           f'Captured {e(binder.captured_at)} (device UTC)</p></header>',
           '<p class="instructions">Read this file offline in a browser. Use the browser’s Print command '
           'for a paper copy. Check print preview and page count before printing; layout depends on the browser. '
           'No content is downloaded by this document.</p>',
           f'<p class="notice">{e(NOTICE)}</p>',
           f'<p class="{"private" if binder.include_notes else "meta"}">'
           f'{"PRIVATE ARTICLE NOTES INCLUDED — protect this copy." if binder.include_notes else "Private article notes excluded."} '
           'Article bodies and the binder title may still contain private information.</p>',
           '<nav aria-label="Contents"><h2>Contents</h2><ol>']
    for index, entry in enumerate(binder.entries, 1):
        out.append(f'<li><a href="#article-{index}">{e(entry.article.title)}</a>'
                   f' <span class="meta">— {e(entry.article.category)}</span></li>')
    out.append('</ol></nav>')
    total = 0
    for index, entry in enumerate(binder.entries, 1):
        article = entry.article
        if not isinstance(article, KnowledgeArticle):
            raise ValueError("invalid binder entry")
        if not binder.include_notes and entry.note is not None:
            raise ValueError("private note present without opt-in")
        if binder.include_notes and not isinstance(entry.note, str):
            raise ValueError("invalid private note")
        total += len(article.body.encode("utf-8")) + len((entry.note or "").encode("utf-8"))
        if total > MAX_TEXT_BYTES:
            raise ValueError("binder exceeds the 8 MiB text limit")
        out.extend([f'<article class="entry" id="article-{index}">',
                    f'<div class="eyebrow">REFERENCE {index:02d} / {len(binder.entries):02d}</div>',
                    f'<h2>{e(article.title)}</h2>',
                    '<p class="notice">Full captured article below. Check its scope, conditions and source. '
                    'Imported instructions and source labels have not been independently verified by this export.</p><dl>'])
        metadata = (("Article ID", article.slug), ("Category", article.category),
                    ("Source title", article.source_title), ("Publisher / author", article.source_publisher),
                    ("Source URL (not fetched)", article.source_url), ("Review date (supplied)", article.reviewed_on),
                    ("Safety label (supplied)", article.safety_level), ("Rights / license", article.license),
                    ("Original body SHA-256", article.checksum))
        for label, value in metadata:
            out.append(f'<dt>{e(label)}</dt><dd>{e(value or "Not supplied — verify before relying or sharing")}</dd>')
        # Numeric CR entities avoid HTML parser CR/CRLF normalization. Browsers
        # can still visually wrap/shape text; the original body hash identifies it.
        body = e(article.body).replace("\r", "&#13;")
        out.append(f'</dl><h3>Full article text</h3><div class="body">{body}</div>')
        if binder.include_notes:
            note = e(entry.note).replace("\r", "&#13;")
            out.append('<aside class="note"><h3>Private article note — not source guidance</h3>'
                       f'<div class="note-body">{note or "No saved note for this article."}</div></aside>')
        out.append('</article>')
    out.append(f'<footer>{e(PRIVACY)} This file does not update itself. It is not a database backup '
               'or an importable knowledge pack. Rebuild to capture later article changes.</footer></main></body></html>')
    encoded = "\n".join(out).encode("utf-8")
    if len(encoded) > MAX_HTML_BYTES:
        raise ValueError("rendered binder exceeds the 64 MiB file limit")
    return encoded


@dataclass(frozen=True)
class SavedBinder:
    path: Path
    sha256: str
    bytes_written: int


def save_binder(binder: FieldBinder, destination: str | Path, *, acknowledged: bool = False) -> SavedBinder:
    """Exclusive-create only; no overwrite, no hard-link filesystem requirement.

    On normal I/O errors remove only the partial file created here. Abrupt power
    loss can leave a partial new file: this is not atomic publication or a backup.
    """
    if acknowledged is not True:
        raise ValueError("confirm copying rights and the unencrypted export/privacy notice")
    path = Path(destination).expanduser().absolute()
    if path.suffix.lower() not in {".html", ".htm"}:
        raise ValueError("choose a NEW .html filename for the field binder")
    encoded = render_binder(binder)
    identity = None
    try:
        with path.open("xb") as stream:
            identity = os.fstat(stream.fileno())
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        # Do not delete someone else's pre-existing or substituted file.
        if identity is not None:
            try:
                current = path.lstat()
                if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                    path.unlink()
            except OSError:
                pass
        raise
    return SavedBinder(path.resolve(), hashlib.sha256(encoded).hexdigest(), len(encoded))


def open_saved_binder(saved: SavedBinder) -> bool:
    """Explicit user action; verify the same generated file before requesting a browser."""
    if not isinstance(saved, SavedBinder) or saved.path.suffix.lower() not in {".html", ".htm"}:
        raise ValueError("save a binder first")
    with saved.path.open("rb") as stream:
        content = stream.read(MAX_HTML_BYTES + 1)
    if len(content) != saved.bytes_written or hashlib.sha256(content).hexdigest() != saved.sha256:
        raise ValueError("saved binder changed; build and save a new copy before opening it")
    return webbrowser.open(saved.path.as_uri(), new=2)
