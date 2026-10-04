# Printable Field Binder

## What is implemented

**Knowledge Library → Field Binder…** builds a portable, self-contained HTML
reference collection from the currently open article or all library bookmarks.
The latter is explicitly independent of the library's current search/category
filters and pagination. It does not silently select only the visible first page.
The programmatic capture API can also accept an ordered tuple of article IDs.
No articles, emergency recommendations, language model, or new curriculum are
added by this change. The existing twelve starter articles retain their review
limitations.

Build a preview, check the included titles and source labels, confirm copying
permission/privacy, then **Save NEW binder HTML…**. You can open the saved file
in a browser without FieldForge or Python and use the browser's Print command.
The application's separate **Open saved binder / print…** action requires another
confirmation and only requests opening the local file. It never submits a print
job or claims a paper copy was produced. Printer/browser settings, page counts,
fonts and pagination remain environment-dependent: inspect print preview first.

The file has a contents list, full article text, per-article source title,
publisher, supplied review/safety/rights fields, and original body checksum.
Article sections start new pages under print CSS. Full text is included, not
search snippets or AI summaries. Markdown/HTML inside an article is displayed as
plain text, not rendered or executed. Missing source/review/rights labels remain
missing rather than being filled with a false review date or public-domain claim.
The capture timestamp is the device's UTC clock, not a verified source date.

## Preview and data integrity

Capture uses a single read-only SQLite transaction and exact article IDs. All
selected articles must still exist and their body hashes must match their stored
checksums. A missing or corrupt article aborts the entire preview instead of
silently omitting it. No index rebuild, schema migration, article mutation,
bookmark change, or export-history write occurs during capture.

Limits are 50 articles and 8 MiB of combined body/optional-note UTF-8 text, with a
64 MiB rendered-file ceiling. Exceeded limits fail explicitly, not by truncating
a collection. The graphical per-article preview displays at most 20,000 characters
and labels that limit; the full captured article is still in the saved output.
Use a smaller collection when necessary. This is not a large-corpus streaming
export, book-layout system, or global duplicate detector.

Captured articles and optional notes stay in memory until the dialog closes.
Later database edits or bookmark changes do not substitute a different version
into an already-previewed binder. Rebuild the preview to refresh it. Changing
binder title, selection mode, or note inclusion clears the prior preview and
copying confirmation. Cancelling a read discards the result without writing a
file. Normal closing is blocked during file saving so a completed write is not
misreported as cancellation.

## Privacy and copying rights

**Private article notes are excluded by default**, independently of the older
JSON-pack privacy checkbox. Including them requires explicit confirmation before
preview and produces conspicuous private-copy labels in the output. Article-note
text is identified separately from source guidance. Household records, inventory,
learning notes and emergency records are not read or exported by this feature.
However, private information deliberately placed inside an article body or binder
title remains in that text. Bookmarked titles may themselves disclose interests.

The output is **unencrypted** and readable by anyone with the file or paper copy.
Use only material you have permission to copy; metadata and the acknowledgment
checkbox are not a licensing validator. Source hashes detect changed body text,
not publisher authenticity, content accuracy, medical safety or redistribution
rights. Removing a file does not securely erase backups or printer spools.

Opening the dialog first saves the current library article note, then holds the
existing library busy guard so ordinary tab changes, closing and backup do not
bypass that modal workflow. Saving the note does not opt it into the binder.
Unsaved notes in other application processes are not captured. After closing the
dialog the guard is released, including on construction failure.

## HTML security and offline behavior

All document text, source fields, note text and user-supplied titles are escaped
with Python's `html.escape`. Article/source identifiers never become HTML IDs or
attribute markup. Contents links use generated numeric fragment IDs only. Source
URLs are inert text, not outbound links. There are no scripts, image tags,
external styles, fonts, remote embeds, or active Markdown links. Fixed inline CSS
and a restrictive Content Security Policy provide an additional boundary.

Unicode/text is retained; CR characters are represented by numeric references to
avoid HTML's source newline normalization. Browser font rendering and visual
wrapping are not byte-level reproduction. The body checksum refers to the
original captured UTF-8 body, not the rendered HTML file. The saved result has a
separate HTML-file hash.

The in-app Open action checks the file against that saved hash before asking the
default browser to open a local file URI. This catches subsequent accidental
changes, not a hostile local actor racing filesystem operations. Browser
extensions, history and other browser traffic are outside FieldForge's control.
The generated document itself has no network-dependent resource. A user-chosen
cloud/network filesystem can still contact its provider.

## File creation and portability

Saving only creates a **new** `.html`/`.htm` file, using exclusive creation.
Existing paths, including symlinks, are not overwritten. A normal write/flush
error triggers cleanup of the newly created partial file, not someone else's
existing file. No hard-link support is required by this writer. Unlike the full
snapshot publication workflow, this path does not require an NTFS/ext4-style
hard-link-capable destination. That is not hardware validation on every USB
filesystem.

Publication is **not atomic**: another process may observe a partial file while
writing, and abrupt process/power loss may leave one. The UI only reports success
after write, flush and fsync return. This feature is a portable reading copy,
not an integrity-checked recovery archive, transactional update mechanism or
importable knowledge pack. The binder never auto-updates. Keep the database and
full snapshot recovery workflow for editable/recoverable records.

## Tests and updating

New tests cover read-only capture, consistent snapshots during concurrent writes,
bookmarks beyond UI filters, corruption/size/selection errors, exact body/context,
default note exclusion (including no note-column read), opt-in note labels,
HTML/attribute/script escaping, new-file protection, I/O cleanup, no-hard-link
writing, explicit/verified browser requests, actual Tk preview/save/cancel
workflows and full Knowledge Library integration. GUI tests need a display and
are added to Linux graphical and hosted Windows test commands.

The local container cannot resolve GitHub for a full clone; local targeted tests
use the exact fetched library implementation verified against its Git blob hash.
Full-checkout regressions/integration and platform CI outcomes must be checked
for the published commit, not assumed from the local subset. Browser inspection
is separate from Tk tests; no physical printer or every-browser compatibility is
claimed.

Update application source for the new button; an article JSON pack cannot install
it and existing downloaded ZIPs do not auto-update. Close the old app and back up
its database before changing builds. A saved HTML binder, however, can be opened
without updating FieldForge. This is an unmerged development feature, not a release.

Technical references consulted:
- Python HTML escaping: https://docs.python.org/3/library/html.html
- Tkinter threading/event model: https://docs.python.org/3/library/tkinter.html
- W3C Content Security Policy: https://www.w3.org/TR/CSP/
- W3C paged-media CSS: https://www.w3.org/TR/css-page-3/
