# Preview-first local text import

## Delivered in this slice

A new **Import Text Document…** button in the desktop Knowledge Library and its
standalone reader. It adds one local UTF-8 text or Markdown file as one searchable
article. No knowledge-pack JSON or command line is required. There is no new
runtime dependency, content download, model, PDF reader, OCR system, or automatic
folder scan. The existing twelve starter articles are unchanged.

1. Choose a `.txt`, `.md`, or `.markdown` file.
2. Inspect the captured text under **Text preview**.
3. Check **Article details & source**: title, category, ID, tags, source title,
   author/publisher, source URL, rights, review date, and safety label.
4. Confirm that you have permission to store the text and understand the
   article-export privacy notice, then choose **Add previewed document**.

`examples/equipment-ledger.md` is an original recordkeeping/software exercise
for testing this flow. It is not a new reviewed technical manual.

## Exact-text and resource boundaries

Only regular files are accepted, up to 2 MiB and 2,000,000 decoded characters.
A bounded read also catches a file that grew after the initial size check.
On POSIX, opening a named pipe does not wait for a writer; non-regular files are
rejected. File handles close even on read/validation failures.

Decoding is strict UTF-8 with an optional initial UTF-8 BOM removed. There is no
encoding guessing, lossy replacement, Markdown rendering, newline normalization,
HTML/script evaluation, image fetch, or external URL access. Unicode, tabs, CRLF
and trailing whitespace are otherwise preserved. Binary/control characters,
empty text and unsupported formats produce actionable errors.

The preview displays at most 20,000 characters and explicitly labels larger
texts as a partial preview. The entire captured text is imported, never silently
truncated to the preview size. Edit/split files outside FieldForge before loading
when needed. This version has no in-app body editor or automatic chapter split.

An immutable in-memory snapshot is used for the import. Changing/deleting the
original file after preview cannot silently substitute new text. Choose the file
again to capture an edited version. The captured input-file hash is shown in the
dialog; the stored article retains its existing body hash. These hashes may differ
when a BOM is removed. The input-file hash is not separately persisted as a
provenance record. A hash is an integrity identifier, not proof of authenticity.

## No automatic replacement

The default article ID is `local-` followed by the full SHA-256 of the decoded
body. It is independent of the filename. Identical text and metadata under that
ID produce an **unchanged** result, not a duplicate. Existing differing text,
metadata, or a mismatched stored checksum cause an explicit conflict: nothing is
replaced. Change the ID only to deliberately create a separate article.

This is not global duplicate detection. The same body can exist under another ID;
renaming a file can change its suggested title, so review title/metadata when
reimporting. New text gets a new suggested ID; edition/version management is not
implemented. User edits and article annotations are never overwritten.

The existence check and insertion occur in the same SQLite write transaction.
Concurrent imports cannot silently replace one another. A database exception
rolls back the attempted insert and its search-index changes. The default
10-second database timeout is inherited from the library.

## Privacy, provenance, and sharing

The source path is not persisted. The filename is only used to suggest an editable
title; it becomes part of the article only if accepted as the title or manually
copied into metadata/text. Source, license, publisher and review fields start
blank, with a default caution label. Nothing is automatically labeled verified,
reviewed, public domain, or redistributable. Supplied metadata is not independent
verification, and there is no legal-rights validation service.

**Imported bodies are articles, not private notes.** They are searched by Library
and Ask Library and included in ordinary article-pack exports, even when the
Include private notes checkbox is off. The dialog displays this prominently and
requires acknowledgment. Do not import passwords or private household/medical
records here. A full private-document vault and per-article sharing permissions
remain future work. Fields/body intentionally containing personal data are not
automatically redacted. The database and knowledge packs are unencrypted.

Bookmarks and private notes remain separate and keep their existing export rules.
Whole-database snapshots include imported articles, metadata and annotations.
Knowledge packs retain the existing article format, so exported text articles
can be read by earlier compatible readers. Plain-text files themselves must use
the new button, not the JSON Import Pack button.

The importer makes no network requests. Select files already stored locally for
offline operation; OS/network/cloud-mounted filesystems can still contact their
provider when the user opens a path. No claim of secure memory erasure is made.

## UI lifecycle and updates

File reading and database insertion run in a worker; Tk runs on the main thread.
Cancelling a read discards the late result and never writes to the database.
Normal close is blocked during a save so a completed import is not reported as
cancelled. A forced process exit can still interrupt work. SQLite transaction
behavior provides the persistence boundary, not a promise of hardware-failure
immunity.

Opening the dialog first saves the current article note, and respects the existing
library busy/save-failure guard. The modal dialog also holds that guard against
normal application close. Completion clears hiding filters and refreshes the
library; an imported item not on the first page remains accessible through search.

A downloaded source ZIP does not update automatically. Back up the database and
close the old application before using an updated checkout. Importing a JSON pack
cannot add this new interface. Windows/macOS hardware validation is separate from
Linux GUI tests; this is not a signed installer or mobile build.

## Verification

New tests exercise strict decoding, bounds, control characters, regular-file
checks, exact snapshots, metadata validation, acknowledgment, no-overwrite
behavior, identical/conflicting concurrency, rollback, no-network operation,
real Tk file-picker/preview/confirmation/cancellation, and source/pack/snapshot
integration. The separate `text-import-gui` CI job explicitly requires a working
Tk display and runs the text-import UI and actual Knowledge Library integration
under Xvfb. Baseline headless tests can still skip other display-dependent tests.

Technical references consulted:
- Python codecs / utf-8-sig: https://docs.python.org/3.13/library/codecs.html
- Python sqlite3 transactions and lifecycle: https://docs.python.org/3.13/library/sqlite3.html
- Tkinter threading model: https://docs.python.org/3/library/tkinter.html
