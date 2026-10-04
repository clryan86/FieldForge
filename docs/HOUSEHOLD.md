# Household profiles: people, pets and explicit planning assumptions

## Delivered

**Inventory** now contains two subpages: **Supplies** and **Household**. The
Household page replaces the add-only quick form. It can list, filter, add, edit
and remove existing household profiles, with Adult/Child/Pet labels and private
planning notes. No profiles or personal details are imported from the user's
account or conversations. Examples and tests use fictional data only.

New profiles require explicit water and calorie planning allowances: the fields
start blank, not at adult defaults. Changing Adult/Child/Pet does not change an
allowance automatically. Existing profiles open with their existing values.
These fields are inventory-planning assumptions, not recommended intake,
nutrition, medical treatment or animal feeding guidance. Source appropriate
allowances from your own care/preparedness plan; the application does not derive
needs from age, species, weight or a medical condition.

The overview distinguishes people, children (a subset of people) and pets. Its
allowance totals include all saved profiles, even when a search hides some rows.
This matches the existing combined household resource arithmetic: it does NOT
allocate food by species, match individual dietary requirements, or prove a
particular supply is safe/suitable for a particular person or animal. The editor
requires a second confirmation for a zero-calorie allowance; this excludes the
profile from calorie demand and is not an instruction to eat/feed nothing.
Water must be positive under the existing model. Unknown allowances cannot yet
be represented separately from a missing profile; partial/unknown-demand schema
and per-person/per-species allocations remain future work.

## Use

Select **Inventory → Household → Add person / pet**, or select an existing row
and **Edit selected profile**. Enter a name/alias, profile kind, liters/day,
whole-number kcal/day, and an optional note. Save explicitly. Cancelling a dirty
form requires confirmation. The listing does not show private note bodies; open
a profile to view or change its note. Search matches names/aliases only, not notes.
Lists are paginated in groups of 50.

Changes saved through this page refresh the dashboard immediately. Removal
requires confirmation and changes future household totals, but does not alter
inventory. The application does not silently delete other members or consolidate
duplicate names: multiple people/animals may legitimately share an alias.
An open household editor blocks normal application close and the backup action
until it is saved or cancelled. Backup still cannot save unsaved edits in a
separate process. Refresh to pick up other windows' changes.

## Conflict protection and storage

The service uses existing `household_members` and `app_events` tables; it does not
create a schema or migrate records. Every displayed profile carries a fingerprint
of its stored row. The save/remove operation checks that row inside the same
SQLite write transaction as its update and minimal change-event insertion.
Concurrent/stale edits therefore fail instead of silently replacing newer data,
including changes made by older APIs. Failed saves keep the visible edits intact:
copy what you need, cancel, refresh and reopen the current record to reconcile.
The content token is not a monotonic revision; a row changed and then restored
exactly to its earlier state has the same fingerprint.

New change events contain only the operation, member ID and changed field names.
**They do not duplicate names, note text or allowance values into event history.**
An event failure rolls back the household write. Identical saves add no event.
This is minimal history, not a full before/after audit or undo feature. Existing
CLI/direct database APIs retain their behavior and do not automatically gain
these checks or events.

Profiles and notes remain unencrypted. They are included in full SQLite snapshots
and the older private household JSON backup, but not ordinary article-sharing
packs or the article-only Ask Library retrieval. Explicitly placing private data
in an article still makes that article searchable/exportable. Profile removal is
not secure deletion from SQLite free pages, other local copies or old backups.
Use aliases and only necessary information; no password/private-document vault
or encryption is added by this milestone.

## Validation and compatibility

The new service rejects nonfinite, negative or over-bound numeric inputs, invalid
booleans, Child+Pet ambiguity, and malformed editor values. Water is a positive
number and calories a nonnegative integer, each at most 1,000,000,000. This is a
software ceiling, not a physically appropriate allowance. Name/alias is limited
to 200 characters; notes to 10,000 without NUL. Names are trimmed; notes preserve
exact Unicode, whitespace and line endings. Existing malformed records may need
correction or a compatible recovery copy before summaries can be shown.

The UI uses short local database operations with a 250 ms SQLite lock wait;
this is not a hard real-time or very-large-roster performance guarantee. There
are no network calls, model dependencies or downloads. A user-selected remote
filesystem can still involve its provider. No base-model defaults or existing
calculator formulas are changed. There is no permanent deactivate/return state,
medical assessment, automatic demand calculation, or undo/history browser yet.

## Verification

Targeted tests use the exact repository domain model and synthetic tables matching
the current household/event definitions. They cover explicit values, flags, limits,
Unicode notes, no-overwrite conflicts, legacy writes, concurrent saves, atomic
rollback, minimal event privacy, filters/pagination, real Tk editing/cancellation,
zero-value confirmation, close guards, stale-data failure states and visible
controls. Additional full-checkout tests cover real-app dashboard/backup guards,
legacy and full backup compatibility, the actual calculators, unchanged schema
and privacy separation from article exports/search.

Linux graphical and hosted Windows CI commands include the new workflow. Their
results must be checked for the exact commit; adding tests alone is not evidence
of a pass. Local graphical tests are Linux tests, not a claim about the user's
specific Windows computer or Apple/mobile platforms.

Update application source to get this screen; content JSON cannot install it.
Downloaded ZIPs do not auto-update. Close the old app and back up its database
before running an updated build. This is a draft-branch change, not a release.

Technical references consulted for transaction/lifecycle implementation:
- https://docs.python.org/3.13/library/sqlite3.html
- https://www.sqlite.org/lang_transaction.html
