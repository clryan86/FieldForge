# Civilization Pathways — development milestone

Catalog version: `2026-10-01.1`. Progress schema version: `1`.

## What this actually adds

An offline learning-map explorer with 24 proposed goals grouped into six learning
stages. The map is not a set of 24 installed lessons and is not the finished
civilization-rebuilding curriculum. It links the 12 existing starter articles
where they offer related introductory reading. It does not add a model, download
books, or claim the introductory text has received specialist review.

Stages are a navigation aid, not a disaster-severity scale, a countdown, a
prediction of collapse, or a mandate to attempt activities in that order. People
may browse any stage and record prior experience. A prerequisite graph is a
proposed educational organization, not a claim that prerequisites alone make a
project feasible or safe.

## Desktop use

Open **Civilization Pathways** in the updated desktop application. The tab has:

- A searchable, stage-grouped topic tree and content-availability filters.
- **Overview**: an objective, a bounded planning exercise, resource/training gaps,
  and prerequisite practice not yet recorded.
- **Study plan**: all direct and indirect prerequisite goals, each listed once in
  dependency order. Select a step and use **Explore selected step** to navigate.
- **Local reading**: real locally stored text for the explicitly linked article
  IDs. Opening an article never records practice or contacts a source website.
- **My progress**: a self-reported status and private learning note.

The three material labels mean:

| Label | Meaning |
|---|---|
| Intro available | At least one linked introductory article is installed. Not a complete course. |
| Intro not installed | This goal has starter links, but none of those articles is installed. |
| Guide needed | This catalog has not linked a dedicated guide. Other imported library content may still be relevant. |

Mappings match explicit article IDs, not similar titles. This avoids claiming a
random text is an appropriate lesson, but arbitrary new packs are not
semantically matched to goals. Browse/search the main library for other material.
Future work includes reviewed mappings and user-managed reading associations.

**Next to explore** shows unfinished goals with linked reading installed and all
ancestor prerequisites marked as practiced. That is a study suggestion based on
self-reports, never a safety clearance or certification. If a prerequisite is
changed to Needs review, descendants no longer qualify for that view until the
practice record is updated. Reading a page never changes these records.

## Saving, concurrency, and privacy

Statuses are `not_started`, `exploring`, `practiced` (displayed as **Practice
recorded**), and `needs_review`. There is deliberately no score or claim of
verified mastery. One database currently contains one shared learning record,
not separate profiles for every household member.

Notes preserve exact whitespace and Unicode, are limited to 20,000 characters,
and cannot contain NUL characters. Save explicitly, press Ctrl+S in the editor,
or leave the goal normally. Desktop tab navigation and normal application close
also save. A failed save keeps the text visible and blocks leaving the tab or
normal close. A crash/power loss can still lose unsaved text: this is not a
keystroke journal.

Each saved row has a revision token. Writes compare the revision inside a SQLite
write transaction, so a stale editor cannot silently overwrite another window's
changes. **Reload saved progress** asks before discarding dirty text. Copy edits
before reloading to reconcile a conflict; automatic merging is not attempted.

`pathway_progress` is an additive table in the same SQLite database as the
library. Opening the map does not insert articles or mark progress complete.
Reopening does not reset records. Unknown future progress schema versions are
rejected without rewriting their version. Rows for goals absent from a newer or
smaller catalog are retained rather than deleted.

**Whole-database snapshots include pathway progress and notes.** The legacy
household JSON export does not. Article knowledge packs do not include pathway
progress, even when their Include private notes option is selected: that option
applies to article bookmarks/notes. For a full personal recovery copy, use the
complete SQLite snapshot feature. Snapshots and this local database are
unencrypted and should be protected as private information.

## Windows launch convenience

`Start FieldForge.cmd` is included in the repository root. Extract the full source
ZIP to a folder, then double-click that file. Do not run it from inside the ZIP or
as administrator. Python 3.10+ with the `py` launcher and Tkinter must already be
installed. This launcher does not install software, alter execution policies,
contact a network, or update your downloaded source code.

It uses the existing `FIELDFORGE_DB` override when set. Otherwise it opens
`%USERPROFILE%\.fieldforge\playground.db`, matching the earlier Windows playground
instructions. It prints the database location and leaves the console open on
failure. It is a source launcher, not a signed Windows installer.

For a standalone pathways window, from the repository root:

```sh
python -m fieldforge.ui.pathways
```

Use `py` instead of `python` with the Windows launcher when appropriate. The
standalone command follows the normal `FIELDFORGE_DB` setting/default database;
unlike the convenience batch launcher, it does not select playground.db itself.

Downloading changes from GitHub and importing an article pack are different:
a JSON pack cannot install this new interface. Update the source code to get the
new tab and launcher. Existing data resides outside the source folder by default;
back it up before changing builds, and close the old application first.

## Verification and development

New tests exercise graph cycles/unknown references/diamond dependencies,
deterministic plans, exact reading availability, transitive prerequisites,
Unicode note persistence, validation, additive initialization, unknown-schema
protection, transactional failures, concurrent/stale saves, no-network operation,
actual Tk navigation, references, conflicts, and desktop notebook integration.

Full-checkout integration tests also verify that the map's reading IDs all exist
in the starter bundle, that article exports exclude learning notes, and that a
whole-database snapshot restores progress along with articles and article notes.
Run the graphical tests with a display, for example on Linux:

```sh
xvfb-run -a python -m pytest -q tests/test_pathways.py tests/test_pathways_ui.py
python -m pytest -q tests/test_pathways_integration.py
```

GUI tests skip when Tk/display is unavailable. A headless CI pass is not Windows,
macOS, Android, or iOS graphical testing. The batch launcher requires separate
Windows validation; Linux tests do not establish its behavior on Windows hardware.

Technical references consulted for this implementation:
- Python ttk widget/event documentation: https://docs.python.org/3/library/tkinter.ttk.html
- Python sqlite3 transactions and lifecycle: https://docs.python.org/3/library/sqlite3.html

No additional third-party curriculum text or media is reproduced. Objectives
and exercises are original planning proposals, not independently validated
instructional standards. This slice does not change the project's licensing.
