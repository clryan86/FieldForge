# Your own checklist tasks and responsibility labels

## Delivered

The updated Emergency Mode builds on saved incidents/exercises. Choose a saved,
active record and **Add own task…** to add a title, description, manual priority
and optional responsible name/alias. It starts **Pending**, never automatically
Done. Select **Update selected action…** to record progress or responsibility.
User-added tasks can also have their title, description and priority corrected.
The default custom priority is medium, not an inferred hazard assessment.
A task whose title/description/priority changes cannot keep a Done status in
that save; set it to Pending, In progress or Blocked and review the changed task.

Every action is labeled **Scenario prompt** or **User-added** in the list and
detail view. Existing scenario wording and priority remain read-only; a custom
action cannot silently replace an original prompt. The incident's original
template checksum remains unchanged and does not cover custom additions, later
progress, or assignments. No new reviewed guidance or reference collection is
added by this software change.

Responsibility is a local text label, not a user account, automatic household
lookup, notification, proof of acceptance, or qualification. Contact the person
separately. Blank labels show **Unassigned**. Use aliases and only necessary
information. These names are not pulled from the user's ChatGPT/GitHub profile.

Custom tasks append in saved order. They are not automatically reordered by
priority, and no priority or completion count certifies safety. Marking a task
Done is still self-reported; official instructions and immediate life-safety
needs take precedence. Archived incidents remain read-only until explicitly
reopened, with all prior notes and assignments retained.

## Persistence and compatibility

One additive table, `emergency_action_metadata`, stores task origin and the
responsibility label. The existing `emergency_state` table carries a separate
`action_metadata_schema=1` marker. No original scenario, household, supply, article,
or journal record is migrated or reset. Old saved task rows without metadata
remain scenario prompts with no assigned label. Unknown, unversioned or missing
metadata structures are rejected instead of silently rebuilding them.

The existing task revision now guards responsibility and custom-text changes
as well as status/notes through the new service. Writes update the task, its
metadata, incident revision and activity entry in one transaction. Two stale
editors cannot silently replace each other's assignments. Adding a task also
checks the incident revision shown when its editor opened. If another window
changed that incident, keep/copy your entered text, cancel, refresh and retry.
Failed saves keep edits visible. Activity records indicate which kind of change
occurred without copying task descriptions, responsible labels or private notes
into another field.

The original status-only API remains usable and does not delete metadata. Older
application screens cannot show origin/responsibility, though they retain the
task rows and metadata. Use updated source to see these distinctions, rather
than relying on an older copied checklist. This is additive compatibility, not
a guarantee that an arbitrary external database editor preserves invariants.

The workflow is bounded to 200 tasks per incident, including scenario prompts.
Custom titles are up to 200 characters, descriptions and private notes up to
4,000, and single-line responsibility labels up to 120. Assignment labels and
titles are trimmed; descriptions and private notes preserve their text. A
Blocked status still requires an explanatory note. There is no automatic task
assignment, deletion, reassignment notification, schedule, custom template
manager or shift acknowledgment in this milestone.

## Copying and backups

**Copy checklist (no notes / assignees)** includes the incident title, task
titles/descriptions, priorities, statuses and origin labels. It excludes the
responsibility field, private task notes and journal entries. Personal text
manually put into titles/descriptions is still copied. This is an explicit
system-clipboard operation, not secure redaction and not a recovery backup.

Whole SQLite snapshots include the added metadata, custom tasks and notes.
Ordinary article JSON packs and the article-only Ask Library search do not query
these tables, even if article-note export is enabled. The old household-only
JSON export is not an incident backup. Stored records, clipboard contents and
snapshot files are unencrypted. Removing local files is not secure erasure.

## Interface and verification

The existing modal-editor close/backup guards cover the new task editor. Save
or confirm discarding edits before closing. A queued repeated Treeview selection
event now preserves the selected task instead of clearing a just-made selection.
Short database work uses the existing 250 ms SQLite lock wait; this is not a
hard-real-time or failure-proof emergency communications system.

Targeted tests use the exact existing emergency engine, schema and model files,
not a substitute implementation. They cover all five unchanged templates,
upgrade from saved v1 records, custom text/alias persistence, concurrency,
transaction rollback, archive/reopen, bounds, copy privacy, metadata version
checks, no-network operation and actual Tk interactions. Four additional
full-checkout tests exercise complete recovery, private-data separation,
unchanged unrelated app data and the actual desktop close/backup integration.
Linux GUI and hosted Windows CI include the new workflow; their result must be
checked for the precise commit before claiming a pass.

Updated application files are needed; a downloaded ZIP does not auto-update
and importing an article pack does not add this interface. Close the old app and
back up its database before changing builds. No merge, release, installer,
local AI model or mobile package is implied by this draft milestone.

Technical documentation consulted:
- SQLite explicit/write transactions: https://www.sqlite.org/lang_transaction.html
- Tkinter ttk widget and selection events: https://docs.python.org/3.10/library/tkinter.ttk.html
