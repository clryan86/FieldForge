# Offline knowledge reader and portable packs

## Implemented in this development branch

The desktop application's **Knowledge Library** tab browses and searches installed
articles, filters by category or bookmarks, displays provenance and safety metadata,
and saves private notes locally. It can import and export JSON knowledge packs.
**Find passages** opens a question search with exact excerpts and source details;
**Open full article** highlights the retrieved passage in the reader. See
[Offline evidence retrieval](OFFLINE_EVIDENCE.md).
Pack I/O runs in a worker so the interface stays responsive; all Tk updates remain
on the UI thread. Notes save on article/search/tab navigation and normal window close.

No account, internet service, telemetry, LLM, embedding service, or cloud API is used
by this subsystem. SQLite FTS5 is preferred. A literal, case-insensitive full-scan
fallback remains usable when FTS5 is absent; it is slower and its substring/accent
matching differs from FTS token matching. Returning to an FTS-capable installation
rebuilds an index invalidated by fallback writes.

This is a **desktop development feature**, not a completed civilization library,
mobile app, or medical decision system. Source metadata and safety labels are
supplied by authors and are not independent verification. A blank review date
means no review date was supplied. Reuse rights are unspecified unless supplied;
no rights to redistribute third-party material are implied.

## Run

After installing the branch, launch the usual desktop application:

```bash
fieldforge-gui
```

The reader can also run independently using only the knowledge subsystem:

```bash
python -m fieldforge.knowledge --database fieldforge.db gui
python -m fieldforge.knowledge --database fieldforge.db list --category education
python -m fieldforge.knowledge --database fieldforge.db list --bookmarked --limit 50 --offset 0
```

`FIELDFORGE_DB` and the default `~/.fieldforge/fieldforge.db` are supported. Put
`--database` before the subcommand. Existing `fieldforge knowledge-add`,
`knowledge-search`, and `knowledge-show` commands remain available. The module
commands add browsing and pack exchange without changing those older commands.

To try the UI with **three software-help examples only**, from the repository root:

```bash
python examples/create_sample_pack.py examples.json
python -m fieldforge.knowledge --database demo.db import examples.json
python -m fieldforge.knowledge --database demo.db gui
```

Examples are not automatically installed into a user's library. A real, licensed,
reviewed survival/civilization corpus still needs to be assembled and validated.

## Content sharing versus personal backup

Export articles without private notes/bookmarks:

```bash
python -m fieldforge.knowledge --database fieldforge.db export knowledge.json
python -m fieldforge.knowledge --database another.db import knowledge.json
```

For a **personal knowledge backup** including notes/bookmarks, opt in on both ends:

```bash
python -m fieldforge.knowledge --database fieldforge.db export private-knowledge.json --include-personal
python -m fieldforge.knowledge --database restore-test.db import private-knowledge.json --restore-personal
```

These are unencrypted JSON files. Protect private backups; do not publish them.
The GUI has a separate private-notes checkbox and export confirmation.

The legacy `fieldforge backup` household JSON format covers only household,
inventory, and waypoints. Use **`fieldforge backup-full`** for a consistent snapshot
of the complete local database, including articles, private notes, and incidents.
See [Full backup and restore](FULL_BACKUP.md) for limits and restoration instructions.

## Import behavior

Identical imports are idempotent. Different existing articles or annotations cause
an error and roll back the entire import by default. Pass `--replace` explicitly
(or select the GUI replacement option and confirm) to replace conflicts. Importing
public article content never deletes or overwrites existing personal annotations.
Personal data requires `--restore-personal`; it is not silently imported.

The complete file, every article, and all annotation references are validated
before writing. The subsequent article/annotation writes run in one SQLite
transaction, including FTS triggers. A late conflict or database error rolls back
earlier writes. This is additive/upsert import, not a destructive restore that
removes records absent from a pack.

Limits: 32 MiB per pack, 10,000 articles, 2,000,000 characters per article body,
100,000 characters per note, search queries up to 512 characters/32 words, and
result pages of 1–500 items. Export size accounting is incremental before building
the final JSON envelope. Very large corpora need a streaming/chunked format later.

## Version-1 JSON contract

An envelope has exactly `format`, `version`, `algorithm`, `checksum`, and `data`.
`format` is `fieldforge-knowledge`, `version` is integer `1`, and `algorithm` is
`sha256`. `data` has exactly `articles` and `annotations` arrays. The envelope
checksum is SHA-256 over UTF-8 JSON of `data`, with sorted keys, no ASCII escaping,
no non-finite numbers, and compact comma/colon separators.

Every article has all `KnowledgeArticle` fields plus `checksum`. `tags` is a JSON
array of strings. Article `checksum` hashes the exact UTF-8 body, including leading
and trailing whitespace. The model includes `license` for a supplied rights
statement, not an inferred license. Annotation entries have exactly `slug`,
`bookmarked` (boolean), and `note`. They must uniquely reference an article in that
pack. Duplicate JSON keys, duplicate article slugs, unknown fields/versions,
malformed dates/types, and broken checksums are rejected.

Checksums detect corruption or mismatched data, **not publisher authenticity**:
someone able to edit a pack can recompute a checksum. Signed publisher manifests,
trusted keys, editorial review, content-version policy and rollback history remain
future work. Imported bodies are shown as text, never executed or rendered as HTML.
Source URLs are displayed as text and never automatically fetched.

## Compatibility and verification

Existing knowledge databases gain an empty `license` column and separate
annotation/state tables. Core household/inventory tables are not rewritten by the
knowledge migration. SQLite connections are explicitly closed after commit or
rollback. Existing draft records affected by the earlier whitespace/hash bug will
fail the export integrity check; reimport the original article rather than silently
relabeling altered content as verified.

Run the new tests:

```bash
pytest tests/test_knowledge_extended.py
xvfb-run -a pytest tests/test_knowledge_ui.py  # Linux virtual-display smoke tests
```

GUI tests skip when Tk or a display is unavailable locally. CI also runs them under
Xvfb with `FIELDFORGE_REQUIRE_GUI=1`, which fails if a display or Tk is missing.
Windows, macOS, iOS, and Android
hardware/build verification is not claimed here. On-device AI/RAG, mobile clients,
installers, reviewed content packs, and offline maps are separate
remaining milestones. This document describes this feature; it does not replace
Codex's architecture/master-roadmap workstream.
