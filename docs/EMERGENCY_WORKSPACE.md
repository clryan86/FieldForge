# Saved Emergency Mode: incident checklists and private activity logs

This milestone replaces the desktop's read-only scenario display with a resumable
workspace. It uses the **existing five scenario templates unchanged**, rather than
adding or claiming to review new emergency advice. Titles and reasons are copied
into each saved record, ordered by their existing priority labels. These are short
planning prompts, not complete procedures. Official instructions and immediate
life-safety needs take precedence. Nothing calls emergency services, determines
location, downloads warnings, or changes stock/household data automatically.

## Start, record progress, resume

Open **Emergency Mode → New incident / exercise…**. Supply a title or alias and
choose an existing template. The dialog previews it before anything is stored.
**Training / exercise** is selected by default; turn it off only when recording a
real incident. Mode is a label, not automatic hazard detection. Creating two
records deliberately makes two independent checklists, even for the same template.

Use **Update selected action** to save Pending, In progress, Blocked, or Done
(self-reported), plus an optional private action note. Blocked requires an
explanation. Completion never means the hazard is cleared, a person is safe, or
professional help is unnecessary. The count is not a readiness score. Progress
is not inferred from reading articles or from incident elapsed time.

Use **Private incident log → Add private log note** for timestamped observations.
Notes are append-only: correct a previous entry with a new note. Automatic activity
entries record creation, status/note changes and archive/reopen events; action-note
bodies are not duplicated into those automatic messages. The current action note
is editable, so an older version is not an audit-history or undo feature.

On reopening FieldForge, select the saved record from the list to resume it. No
record is created or reset just by opening the screen. **Archive record** requires
confirmation and makes it read-only in this workflow; it does not declare an
emergency over. **Include archived** exposes archived records; reopening one keeps
its checklist and notes. The interface offers no delete-all, permanent erasure,
custom-task editor, task assignment, or per-person identity/audit authentication.

## Persistence and concurrency

Four additive tables (`emergency_state`, `emergency_sessions`, `emergency_tasks`,
`emergency_log`) are initialized in one SQLite write transaction. The independent
emergency schema version is 1. Unknown future versions or unversioned partial
emergency tables are rejected without rewriting them. Existing household,
inventory, library and legacy incident entries are not migrated or reset.

Each saved record contains a snapshot/hash of its template. A later software
change to template text cannot silently rewrite the checklist of an existing
incident. The hash identifies the original copied prompt set, not expert review
or a security guarantee. Current task rows and personal notes are not authenticated
against malicious local database editing.

Task and lifecycle writes compare revision numbers inside the write transaction.
A stale editor cannot silently overwrite a newer note/status. An archived incident
rejects task changes and new log notes. Lifecycle operations also notice any task
or log changes since the incident was displayed. Task/session changes and activity
entries commit together or both roll back. Repeating an identical task/lifecycle
save adds no log entry. Separate explicit log-note submissions are separate records.

Editors save only on **Save**. Dirty Cancel requires confirmation. An open editor
blocks normal main-app close and the backup action until saved or cancelled. On a
write conflict, copy any edits needed, cancel, refresh and reopen the current task.
This is not keystroke autosave; a forced process termination can lose unsaved text.
Short operations use a 250 ms SQLite lock wait and run on the UI thread. Very slow
storage can still delay the interface; no hard real-time guarantee is made.

## Time, scope, and privacy

Timestamps use the device clock converted to UTC. They indicate when this software
recorded an entry, not verified incident onset or trusted time. Adjusting the device
clock can affect timestamps; log ordering uses insertion IDs. The screen shows the
latest 100 entries and states the total count. Older entries remain stored and in
full snapshots; full journal browsing/export is not included in this slice.

These are unencrypted private records. Full SQLite snapshots/recovery include all
four tables automatically, with regression coverage. The existing recovery report's
**Incident entries** count still refers to the OLD general `incident_entries` table;
it does not count the new incident-specific log. The older CLI incident journal is
unchanged and not automatically merged into a new session.

Article JSON packs and Ask Library do not query these tables. The old household
JSON backup also excludes them; use a full `.ffbackup` recovery copy. Deliberately
copying private information into an article still makes that article searchable
and exportable. No encryption, redaction, remote synchronization or secure deletion
is added.

**Copy checklist (without notes)** is an explicit clipboard action. It includes
the incident title, mode, task text/statuses, timestamps and template hash, but
excludes private task notes and all log entries. It rereads current saved data
instead of copying stale displayed statuses. The title itself may contain private
information. Protect your system clipboard. This is a copy-friendly summary, not a
full recovery file, printing subsystem or guarantee that another app can print it.

## Verification and updating

Unit/real-Tk tests cover copied templates, independent records, exact Unicode notes,
concurrent edits, log/write rollback, archive/reopen, bounds, future versions,
no-network operation, clipboard exclusion, dirty cancellation, errors and controls
at minimum window sizes. Full-checkout tests cover existing data preservation,
full snapshot recovery, article-search/export privacy and the actual desktop's
close/backup guard. Linux GUI and hosted Windows suites include the new tests.
Observe their result for the exact commit; adding commands does not prove a pass.

Local test execution uses verified copies of the existing scenario engine and
models, not invented substitutes. The development container could not clone via
GitHub DNS; the full repository regression/build runs are performed through CI.
No additional reference content, language model, mobile client or installer is
introduced. No merge or release is implied. Updated application source is needed:
an old source ZIP does not update itself and a JSON content pack cannot add this
screen. Back up data and close the old application before changing builds.

Technical references consulted: Python sqlite3 connection/transaction lifecycle
(https://docs.python.org/3.13/library/sqlite3.html), SQLite transaction control
(https://www.sqlite.org/lang_transaction.html), and Tkinter event/threading behavior
(https://docs.python.org/3.10/library/tkinter.html). No new third-party domain text is
reproduced; the pre-existing scenario module is unchanged.
