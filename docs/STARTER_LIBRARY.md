# FieldForge starter library — 2026-10-01.1

## What is implemented

Twelve locally bundled articles across nine categories. Six are short original
summaries referencing public safety/environment sources; six are original
orientation, recordkeeping, arithmetic, and learning exercises. They are not
copies of the source pages. No page, PDF, video, model, or external asset is
silently downloaded. Source URLs identify attribution, not offline attachments.

This is a small, **AI-drafted and not independently specialist-reviewed** starter
collection. Every article displays that limitation. The `reviewed_on` field is
intentionally empty. Source consultation on 2026-10-01 is not editorial approval.
No publisher endorsement is claimed. High-stakes articles are explicitly labeled.

## Use without a terminal

In the updated desktop Knowledge Library or standalone reader, click **Load
Starter Library**. The worker adds missing articles in one transaction and resets
search/category/bookmark filters so the content is visible. Existing articles,
including edited starters, are never replaced by this button. Private notes and
bookmarks are preserved. Repeating the action creates no duplicates.

The empty state now explains how to load content. An empty search or bookmark
result is distinguished from a database with no installed articles.

### An already-installed reader from PR #1

Use **Import Pack** to select `FieldForge-Starter-Library.json`. Leave both private
note restoration and conflict replacement unchecked. This file uses the existing
version-1 knowledge-pack format and contains no personal annotations. It can be
imported into the user's current reader without upgrading application code.
If a locally edited starter conflicts, do not enable replacement merely to clear
an error; keep the edit and use the updated non-destructive starter button instead.

Updates in GitHub do not automatically update a downloaded ZIP or an installed
application. The new button requires updated source code; the JSON import does not.

## Command-line use

From the repository root, with Python 3.10 or newer:

```sh
python -m fieldforge.knowledge.starter --database ./playground.db install
python -m fieldforge.knowledge.starter export ./FieldForge-Starter-Library.json
```

The `py` launcher can replace `python` on Windows. Export always builds from the
bundled original text in a temporary database, never from a user's articles or
notes. The content is packaged as a Python module, so it is present in a wheel as
well as a source checkout. No package-data glob or network setup is needed.

## Content map and scope

| Category | Included now | Not implied |
|---|---|---|
| Start here | Orientation and limitations | Complete civilization curriculum |
| Emergency planning | Contact and meeting-card worksheet | Live alerts or evacuation routing |
| Water and sanitation | Storage planning; limits of disinfection | Chemical dosing or unknown-water approval |
| Energy | Generator CO precautions; arithmetic power budget | Electrical installation or life-support sizing |
| Outdoor preparedness | Trip equipment-system checklist | Rescue training or offline maps |
| Agriculture | Small backyard compost introduction | Food-production sufficiency or human-waste treatment |
| Logistics | Counting units and estimating supply runway | A guarantee that supplies are safe or adequate |
| Measurement and learning | Measurement exercise; teaching workflow | Professional qualification or structural design |
| Tools and maintenance | Equipment/service record worksheet | Manufacturer manuals or repair procedures |

## Source audit

The following specific pages were consulted on 2026-10-01. Only short original
summaries are bundled. Original worksheets are identified as such, not given
invented external citations.

- CDC, *How to Create an Emergency Water Supply*: https://www.cdc.gov/water-emergency/about/how-to-create-and-store-an-emergency-water-supply.html
- EPA, *Emergency Disinfection of Drinking Water*: https://www.epa.gov/ground-water-and-drinking-water/emergency-disinfection-drinking-water
- CPSC, *Generators and Engine-Driven Tools*: https://www.cpsc.gov/Safety-Education/Safety-Guides/Carbon-Monoxide-Home/Generators-and-Engine-Driven-Tools
- CDC, *Use a Generator Safely*: https://www.cdc.gov/natural-disasters/psa-toolkit/use-a-generator-safely.html
- CPSC, *Carbon Monoxide Fact Sheet*: https://www.cpsc.gov/safety-education/safety-guides/carbon-monoxide/carbon-monoxide-fact-sheet
- PEMA / Ready PA, *Make A Plan*: https://www.pa.gov/agencies/ready/get-prepared/make-a-plan
- US National Park Service, *Ten Essentials*: https://www.nps.gov/articles/10essentials.htm
- EPA, *Composting At Home*: https://www.epa.gov/recycle/composting-home

The project's redistribution license remains unselected. This change does not
relicense third-party source material or the repository. No third-party logos,
images, textbooks, journals, or full articles are copied into this bundle.

## Snapshot corrections in this development slice

`fieldforge snapshot` and `snapshot-restore` retain their archive format. SQLite
connections are now explicitly closed, including before publishing restored files;
a connection context manager alone does not close a handle. Manifest reads are
bounded, duplicate keys and boolean versions are rejected, and partial restore
files are removed after stream failures. Export refuses database/sidecar aliases.

A restore to an existing database still requires `--overwrite`, but now uses the
SQLite backup transaction rather than replacing a file beside a live WAL. New
restores use atomic, non-clobbering hard-link publication; on filesystems without
hard-link support, choose a suitable local destination (for example NTFS or ext4).
Close the app before recovery and prefer a new destination. Integrity/backup work
has a 60-second operational timeout; very large or busy databases may need a later
streaming/recovery implementation. Eight GiB remains the database size ceiling.

Snapshots are **unencrypted**, include private data, and must come from a trusted
source. A digest does not prove publisher identity or guidance correctness. They
cover the SQLite state only, not Python, models, externally stored documents, or
future map/media files. The legacy JSON `backup` command is still a separate,
partial household export.

Technical references:
- Python sqlite3 connection lifecycle and backup: https://docs.python.org/3/library/sqlite3.html
- SQLite online backup transactions: https://www.sqlite.org/backup.html

## Verification boundaries

New local tests cover offline installation/search with and without FTS5, repeat
and concurrent installs, preservation of edits/notes, transaction rollback,
deterministic packs, CLI behavior, actual Tk interactions under Xvfb, connection
closure, WAL backup/recovery, malformed manifests, partial-file cleanup, and
non-clobbering publication races. Local testing is Linux/Python 3.13; Windows and
Apple builds are not claimed from Linux tests. Full pre-existing regressions and
package checks must also pass the PR's CI before this draft is considered ready.

## Still outstanding

Independent content review, larger licensed collections, a dependency-aware
civilization curriculum, local LLM/RAG, mobile applications, maps/media, general
content-update/version conflict resolution, comprehensive recovery tooling,
installers, and a complete accessibility/design pass. The twelve articles do not
make any of those items complete.
