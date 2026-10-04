"""Portable read-only, responsive HTML reader. No service, model or browser storage.

Reuses the binder's validated snapshot and exclusive-create writer. Pocket copies
always exclude private article notes; no JSON pack/database import occurs here.
"""

from __future__ import annotations

import base64
import hashlib
import html
from pathlib import Path

from fieldforge.knowledge import KnowledgeArticle
from fieldforge.knowledge._pocket_assets import SCRIPT, STYLE
from fieldforge.knowledge.binder import (
    MAX_ARTICLES,
    MAX_HTML_BYTES,
    MAX_TEXT_BYTES,
    NOTICE,
    FieldBinder,
    SavedBinder,
    _save_html,
    _title,
    capture_binder,
)


def capture_pocket(database: str | Path, *, slugs: tuple[str, ...] | None = None,
                   bookmarks: bool = False, title: str = "FieldForge Pocket Library") -> FieldBinder:
    return capture_binder(database, slugs=slugs, bookmarks=bookmarks, title=title, include_notes=False)


def _hash_source(value: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(value.encode("utf-8")).digest()).decode("ascii") + "'"


def render_pocket(collection: FieldBinder) -> bytes:
    """All source fields are escaped. The only script/CSS are fixed, hash-allowed assets.

    Full articles exist in the static DOM before JavaScript, including when it is
    disabled. Source URLs are inert text; only generated in-document links exist.
    """
    if not isinstance(collection, FieldBinder) or not 1 <= len(collection.entries) <= MAX_ARTICLES:
        raise ValueError("preview 1–50 articles before creating a pocket reader")
    title = _title(collection.title)
    if collection.include_notes is not False or any(entry.note is not None for entry in collection.entries):
        raise ValueError("Pocket Library never exports private article notes")
    if not isinstance(collection.captured_at, str):
        raise ValueError("invalid capture time")
    if any(not isinstance(entry.article, KnowledgeArticle) for entry in collection.entries):
        raise ValueError("invalid pocket article")
    if len({entry.article.slug for entry in collection.entries}) != len(collection.entries):
        raise ValueError("duplicate pocket article IDs")
    if sum(len(entry.article.body.encode("utf-8")) for entry in collection.entries) > MAX_TEXT_BYTES:
        raise ValueError("pocket collection exceeds the 8 MiB text limit")
    e = html.escape
    policy = (f"default-src 'none'; script-src {_hash_source(SCRIPT)}; style-src {_hash_source(STYLE)}; "
              "connect-src 'none'; img-src 'none'; base-uri 'none'; form-action 'none'; object-src 'none'")
    out = [
        '<!doctype html><html lang="en" data-theme="light" data-size="normal"><head><meta charset="utf-8">',
        f'<meta http-equiv="Content-Security-Policy" content="{e(policy, quote=True)}">',
        '<meta name="referrer" content="no-referrer"><meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<title>{e(title)}</title><style>{STYLE}</style></head><body>',
        '<a class="skip" href="#reading">Skip to reading</a><div class="wrap">',
        '<header><div class="top"><span class="brand">FIELDFORGE</span><span class="badge">OFFLINE READING COPY</span></div>',
        f'<div class="hero"><h1>{e(title)}</h1><p class="sub">Your selected references, ready to read. '
        'No account, server, or Python needed to view this copy.</p>',
        f'<p class="meta">{len(collection.entries)} full articles · Captured {e(collection.captured_at)} (device UTC)</p></div></header>',
        '<p id="fallback" class="hint">Static reading mode. All articles are included below. '
        'Search controls appear only in a browser that allows this file’s built-in script.</p>',
        '<form id="tools" hidden role="search" autocomplete="off">'
        '<label class="search-field" for="query">Search titles and article text'
        '<input id="query" type="search" maxlength="240" placeholder="Find a word or phrase…" autocomplete="off"></label>'
        '<label for="category">Category<select id="category"><option value="">All categories</option></select></label>'
        '<label for="size">Reading size<select id="size"><option value="normal">Standard</option>'
        '<option value="large">Large</option><option value="largest">Largest</option></select></label>'
        '<button id="reset" type="button">Clear filters</button>'
        '<button id="theme" type="button" aria-pressed="false">Dark view</button></form>',
        f'<p id="results" role="status" aria-live="polite">{len(collection.entries)} captured references. '
        'This is not an AI answer or a complete reference collection.</p>',
        '<main class="layout"><nav id="contents" tabindex="-1" aria-label="Library contents"><h3>In this collection</h3><ol>',
    ]
    for index, entry in enumerate(collection.entries, 1):
        article = entry.article
        out.append(f'<li><a class="choice" href="#ref-{index}"><strong>{e(article.title)}</strong>'
                   f'<span>{e(article.category)} · {len(article.body):,} characters</span></a></li>')
    out.extend(['</ol></nav><section id="reading" aria-label="Captured article text" tabindex="-1">',
                '<div id="empty" class="empty" hidden><h2>No matching references</h2><p>Try different words '
                'or clear the category. This only searches the articles included in this file; '
                'it does not prove information is absent elsewhere.</p></div>'])
    for index, entry in enumerate(collection.entries, 1):
        article = entry.article
        metadata = (("Article ID", article.slug), ("Source title", article.source_title),
                    ("Publisher / author", article.source_publisher), ("Source URL (not fetched)", article.source_url),
                    ("Review date (supplied)", article.reviewed_on), ("Safety label (supplied)", article.safety_level),
                    ("Rights / license", article.license), ("Original body SHA-256", article.checksum))
        out.extend([f'<article class="entry" id="ref-{index}"><div class="eyebrow">'
                    f'{index:02d} / {len(collection.entries):02d} · <span class="category">{e(article.category)}</span></div>',
                    f'<h2 tabindex="-1">{e(article.title)}</h2>',
                    f'<p class="warning">{e(NOTICE)}</p>',
                    '<details class="provenance" open><summary>Source, review limits &amp; copying rights</summary><dl>'])
        for label, value in metadata:
            out.append(f'<dt>{e(label)}</dt><dd>{e(value or "Not supplied — verify before relying or sharing")}</dd>')
        body = e(article.body).replace("\r", "&#13;")
        out.extend(['</dl></details>', f'<div class="article-body">{body}</div>',
                    '<div class="reader-actions" hidden><button class="back" type="button">Back to contents</button>'
                    '<button class="print" type="button">Print open article…</button></div></article>'])
    out.extend(['</section></main><footer><p>Private article notes, household records, inventory, learning links and '
                'incident logs are excluded. Article bodies and titles may still contain private text. '
                'This unencrypted file can be read by anyone holding a copy.</p><p>Only copy material you have permission '
                'to store/share. This file is not a database backup or an importable knowledge pack and will not update '
                'itself. PDF-derived articles retain their extraction limitations; original diagrams are not added here. '
                'Search uses literal text matches, not verified answers. Browser extensions/history and file-preview '
                'applications have their own behavior. Test the saved file before depending on it offline.</p></footer></div>',
                f'<script>{SCRIPT}</script></body></html>'])
    encoded = "\n".join(out).encode("utf-8")
    if len(encoded) > MAX_HTML_BYTES:
        raise ValueError("rendered pocket reader exceeds the 64 MiB file limit")
    return encoded


def save_pocket(collection: FieldBinder, destination: str | Path, *, acknowledged: bool = False) -> SavedBinder:
    if acknowledged is not True:
        raise ValueError("confirm copying rights and the unencrypted export/privacy notice")
    return _save_html(render_pocket(collection), destination)
