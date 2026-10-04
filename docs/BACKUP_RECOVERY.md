# Backup & Recovery — graphical recovery without replacing current data

## What is delivered

The desktop has a **Backup & Recovery** tab showing the exact database path used
by that application window. It exposes three operations: create a new verified
backup, inspect a trusted existing archive, and recover the inspected data to a
new database file. Existing files are never overwritten by these GUI operations.
This builds on the existing version-1 `.ffbackup` format; it does not change that
format, the old household JSON export, or article knowledge packs.

**Create verified backup** first asks for confirmation because the archive is
unencrypted and contains private data. After a destination is chosen, the main
app saves pending article notes/bookmarks and pathway progress notes. A failed
save or busy import blocks backup. Committed SQLite data is copied using the
existing snapshot engine, then the resulting archive is decoded into a temporary
database and checked before the new backup file is published.

The check displays counts of household members, inventory, waypoints, incidents,
application events, articles, article-annotation records and learning-progress
records. No private field values are shown in the verification report. Counts
refer to the captured backup, not an ongoing live count. Changes made after the
capture are not retroactively included. Unsaved changes in other application
windows are not included: save them first.

**Inspect backup** requires a trusted-source confirmation. It reads the archive
into temporary storage, verifies its stored database hash and SQLite structural
integrity, and checks recognized record tables/version markers. It never opens
or migrates the currently selected application database. An absent table is
reported as **not present**, not as zero records; older/library-only databases
are explicitly identified as potentially incomplete application backups.
Unknown future version markers, unrelated databases, and malformed expected
tables are rejected. This is a basic shape/version check, not a promise that
every record passes application-level validation or that every article hash was
individually checked. Counts of annotations include stored rows, even if a note
is empty. A version-1 archive has no creation-time field: the UI reports only
**when the inspection ran**, never an invented backup creation date.

**Restore to NEW database** asks for a new filename and explicit confirmation.
It re-reads and re-validates the archive, verifies that the database hash/size
still match the inspected copy, and only then publishes the recovered file.
Changing the archive between preview and restore cannot silently substitute a
different database. Existing files, symlinks, the active database, its sidecars,
and the archive itself cannot be replaced. A destination with existing SQLite
sidecar files is rejected. Choose a new name rather than deleting those files.
An unsuccessful inspection clears any older restore selection to avoid using a
stale success state.

**Open recovered copy** is an additional explicit action. It requests a separate
FieldForge process using the current Python executable, a fixed module name and
an environment variable for that new database; no shell command is assembled.
The current window remains on its original database. Default launch settings
are not changed. A successful launch request does not guarantee the child
application displayed correctly; check its window and any console error. Use the
new window's Backup & Recovery tab to confirm its database path. This interface
does not permanently switch which database the usual launcher opens.

## What is and is not backed up

The backup contains the entire SQLite database state, including supported tables
not individually counted in the report. It is not a backup of the application
source, Python installation, external original documents, local-model files,
map/media files, or the user's entire computer. Text already imported into an
article is in SQLite and is included; a source document merely referenced by a
link is not.

Snapshots are **unencrypted** and contain private records and notes. Choose a
private destination and protect the file. Temporary staging copies are also
unencrypted; they are removed on normal completion/error, not securely erased.
An application crash or power failure may leave staging files. An integrity
check detects accidental corruption; it is not proof of authenticity, safe
medical/technical guidance, or protection against a malicious SQLite archive.
Inspect and restore only trusted backups. The UI does not fetch URLs or send
backup contents to a service. A user-selected network/cloud filesystem may
itself contact its provider; use local storage for offline operation.

Knowledge JSON packs remain a separate sharing format, not full recovery copies.
The older `fieldforge backup` JSON command remains a partial household export and
is not accepted as a `.ffbackup` archive by this screen.

## Operational boundaries

Archive and database work runs on a worker; Tk is touched only on the main thread.
Controls are disabled during operations and normal application close is blocked
until completion. There is no mid-operation Cancel button in this first version.
A forced process termination can still interrupt work; do not mistake a frozen
external filesystem or hardware failure for a completed backup.

The existing snapshot engine's 8 GiB size ceiling and copy/integrity time budgets
remain. This workflow performs read-back validation and temporarily needs space
for archive and decoded database copies. Very large libraries can require
substantial extra space and time. No hardware-level power-loss guarantee is
claimed. The five-second record-summary query budget may reject very large or
unusual databases rather than freezing the UI indefinitely; that is not a
corruption verdict.

New-file publication uses atomic, non-clobbering hard links in the destination
filesystem. Filesystems without hard-link support fail safely: use a suitable
local filesystem such as NTFS/ext4. This is not currently a universal FAT/exFAT
USB-export solution. If the filesystem or permission check fails, no existing
backup is replaced. Another process creating the chosen target after the file
dialog causes a safe failure, not silent overwriting. Close unrelated apps that
may write to a intended recovery destination; this is not a defense against a
malicious local actor racing directory or sidecar changes.

## Standalone recovery

The standalone recovery screen deliberately does not initialize the current
database, so a broken or missing database does not prevent backup inspection:

```sh
python -m fieldforge.ui.recovery
```

It follows `FIELDFORGE_DB` or the usual `~/.fieldforge/fieldforge.db` default.
Unlike the main-app tab, it cannot save unsaved notes in another process; its
help text states this distinction. The Windows `py` launcher can be used in place
of `python`. The new tab needs updated source code; downloaded ZIP files do not
auto-update, and importing a content pack cannot install application features.

## Verification plan and scope

`tests/test_recovery.py` uses synthetic SQLite fixtures for new-file protection,
read-back checking, record counts, source immutability, changed/corrupt archives,
WAL data, future/invalid schemas, publication races, cleanup, no-network behavior,
and explicit child-process launch arguments. It does not contain user records.

`tests/test_recovery_ui.py` exercises the real Tk panel with controlled file
picker/confirmation responses, note-save guards, actual backup/inspection/recovery
workers, stale-selection clearing, failed operations, explicit clipboard use,
minimum window geometry, and main-thread UI callbacks.

`tests/test_recovery_integration.py` requires the full checkout: it verifies all
current application tables, real starter/library/pathway records, actual editor
saves before backup, legacy snapshot compatibility, and the actual desktop tab
and normal-close guard. Linux graphical CI requires a display rather than merely
skipping these tests. A separate Windows/Python 3.12 CI job is added for snapshot,
recovery, UI and full-app integration tests. Its observed outcome must be reported
separately; adding the job is not itself evidence of a Windows pass. Hosted-runner
tests are not validation on every end-user Windows machine or an Apple/mobile
release.

Technical references consulted: Python's sqlite3 connection/backup documentation
(https://docs.python.org/3.13/library/sqlite3.html) and the existing FieldForge
snapshot implementation. No third-party domain content or new runtime dependency
is added by this milestone. No merge or release is implied by the draft PR.

## Explicitly stored original PDFs

The Original PDFs workflow can store complete file bytes in this same database.
Full snapshots therefore include those files and their article associations;
recovery previews show optional original-file/reference counts when present.
External PDFs that were merely text-imported or never stored are still excluded.
Archive/SQLite checks do not validate every original-PDF hash: use Verify bytes
or a verified export after recovery. See [Original PDFs](ORIGINAL_PDFS.md).
