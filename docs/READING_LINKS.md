# Connect imported documents to Civilization Pathways

## Delivered

Choose a goal in **Civilization Pathways → Local reading → Manage reading links…**.
Search or browse installed articles, inspect a source, then **Link previewed
article**. Imported text, PDF-derived articles and existing knowledge-pack
articles all use this same workflow. This does not download material or expand
the shipped starter corpus. A link is your reading choice, not an independently
reviewed curriculum association or a claim that a guide is complete.

The linked article appears in the goal's Local reading list, labeled **Your link**.
Built-in mappings are labeled **Starter** and remain unchanged. The manager does
not allow a duplicate personal link for an article already mapped by that goal.
One article can be linked to multiple goals without duplicating its body. Adding
links does not change the prerequisite graph, mark practice recorded, alter
source/review metadata or qualify someone to perform a task. Imported PDF text
retains its extraction warnings; linking does not restore lost diagrams or
verify that the extraction is correct.

## Version-aware links

Each association records the article slug, a fingerprint of its stored body hash
and source metadata, its title at linking, a device-UTC timestamp and a revision.
Text, title, category, tags, source, license, review-date and safety-label changes
cause the link to show **Source changed — check again**. Private annotation edits
and routine storage-timestamp updates do not change the source version.

The path map compares saved metadata and stored hashes without re-reading every
article body. **Saved version unchanged is not an integrity/authenticity audit.**
Before linking or opening a personal linked source, the service reads its body,
validates the article and verifies the actual body checksum. Bad checksums block
opening/linking even when a lightweight map check appeared unchanged. Hashes do
not prove publisher identity, correctness or medical/technical safety.

Changed or missing personal sources produce **Check reading links** in the map
and appear under **Reading missing / changed**. They are not counted as available
personal reading or silently substituted with a newer source. A goal with such
unresolved links is excluded from **Next to explore**, even if another source is
installed. The prerequisite practice records still determine that study filter;
it is never a safety clearance. Built-in starter availability keeps its previous
behavior, including its independent content-review limitations.

Select a changed item under **My reading links**, inspect its current text, then
explicitly confirm **Update link to this version…**. The update only changes the
association, not the article or your learning progress. Changes made between
preview and saving, or between two editing windows, cause a conflict instead of
a silent overwrite. Keep the original source document and consult appropriately
qualified guidance where needed; this tool is not a subject review service.

Deleting an article leaves a missing-source link visible with its saved title.
Reimporting the identical slug/version makes it available again; different
content still needs an explicit link update. No cascading delete is used for
these associations. **Remove link only…** removes the association, never the
article, article notes or practice records. There is no link-history undo in this
version, and old full backups may retain removed links.

## Storage, privacy and compatibility

One additive table `pathway_reading_links` and its independent
`reading_links_schema=1` marker live in the existing database. Initialization runs
inside the pathway initialization transaction and never seeds sample links.
Unrecognized, missing or unversioned link structures are rejected rather than
silently reset. Links for goals absent from a smaller/newer catalog are retained.
The prior `pathways_schema` and practice records are not migrated or reset.

Associations are personal, unencrypted database records. They are included in
whole-database snapshots, but not article knowledge-pack exports (even with
article-note sharing enabled), field binders or legacy household JSON backups.
Exporting an article does not implicitly reveal which goals you linked it to.
There are no network requests, automatic categorization, notifications or model
calls. Names and metadata from private household/incident tables are not used.

The source chooser displays article text only, not private article annotations.
Its 20,000-character preview limit is labeled; **Open full captured text** displays
the entire source version loaded into the dialog. Source URLs are text and are
not fetched. The manager is not an editor for article content. A filename change
or a new PDF import creating a different article ID is not automatically matched
to an old source association; link the intended article explicitly.

The manager saves pending learning notes before opening and holds the existing
pathway normal-close/backup guard until dismissed. Closing it refreshes the map.
A parent teardown check avoids trying to refresh widgets already destroyed by
an application shutdown. Changing other articles in another application window
requires Refresh to update the displayed map; this is not a filesystem watcher.

## Bounds and remaining work

Up to 50 personal links per goal and 5,000 per database are supported. Selection
uses existing library search, with pages of 25 sources. Small link mutations use
an explicit SQLite write transaction and a 250 ms lock wait; the library search
has its existing timing/performance behavior. These synchronous UI operations
are not a warehouse-scale or hard-real-time performance guarantee. Whole-body
validation is bounded by the existing article model's 2-million-character limit.

The fingerprint records a version, not a copy of the old body. Updating an article
can leave a link pointing to a version no longer stored: retrieve it from your
own backups or explicitly choose the new version. Version comparison is
content-based: returning the article to exactly its former content is treated as
that same version. Link revisions/unique IDs protect against stale update/remove
operations, including remove/recreate sequences. Full-link export/import,
per-person reading profiles, automatic review, multiple source versions and
editable curriculum goals remain future work.

## Verification scope

Targeted tests exercise the actual fetched article library and pathway modules:
FTS/fallback compatibility, additive initialization, captured version checks,
metadata changes, deletion/reimport, no-op/concurrent links, revision conflicts,
rollback, input bounds, lightweight versus full body validation, privacy,
prerequisite behavior and real Tk search/preview/link/update/remove/close flows.
Full-checkout integration tests cover text/PDF-derived article compatibility,
complete recovery, exclusion from article exports/binders and actual desktop
close/backup guards. Existing pathway regression tests are also included in the
updated graphical/platform CI commands.

The local container cannot clone GitHub because its outbound DNS is unavailable.
Local execution uses exact fetched baseline files checked against their Git blob
hashes, not a full checkout. Full regression/Ruff/build/Windows results must come
from CI for the published head. Screenshots use fictional original practice text,
not private user information. No new independent content-review claim is made.

Updated application code is required; downloaded ZIPs do not auto-update and
content JSON cannot install this interface. Close the old application and back
up the database before changing builds. This is a draft-branch feature, not an
installer, local AI model, mobile release or completed civilization corpus.

Technical references consulted:
- https://www.sqlite.org/lang_transaction.html
- https://www.sqlite.org/foreignkeys.html
