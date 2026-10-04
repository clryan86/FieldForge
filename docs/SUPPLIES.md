# Supplies and stock editing

## What this milestone adds

The existing Inventory tab now has a paged, searchable supplies list; a full
supply editor; use/receive controls; and confirmed removal. It works with the
existing inventory and application-event tables, without a schema migration,
network API, new dependency or automatic sample-stock insertion.

Previously the desktop quick-add form did not expose liters, calories or energy
per unit. A water category alone does not tell a calculator how much a bottle
contains. The editor now makes quantity, unit and amount per unit explicit and
shows the multiplication. For example, 6 bottles at 2 liters each record 12 liters.
For food, the kcal field is for the entire unit counted (for example one bag),
not necessarily one labeled serving. No package sizes or conversions are guessed.
Zero means no per-unit amount supplied in this workflow.

Choose **Add supply** or select an existing record and **Edit selected**. The
form exposes name, category, quantity, unit, liters/unit, kcal/unit, Wh/unit,
low-stock threshold, recorded expiry date, location and notes. Scrollable fields
remain reachable in a shorter window. The notes tab is separate from article or
learning notes. Changes only persist on Save supply. Cancelling a dirty editor
requires confirmation; an open editor blocks normal application close.

**Use / receive stock** records a positive quantity in the existing unit, plus a
reason. It rejects overdraws and invalid numbers. Fractional quantities are
supported. This is a stock record, not advice to reduce consumption of medically
required supplies. **Remove record** is a separate, confirmed action; it is not
silently labeled consumption. The list supports category filtering, literal
search over names/locations/units, and pages of 50 records.

## Concurrent edits and change records

Every displayed record has a token derived from its complete stored row. A
mutation compares that token under the same write transaction used for the update
and event insertion. A record changed or deleted since it was displayed is not
silently overwritten. Even changes made through the legacy database quantity API
are detected. If an edit conflicts, its form remains open with the user's edits;
copy anything needed, cancel, refresh and reopen the latest record. Automatic
merging is not attempted. An exact return to the same row state is indistinguishable
from an unchanged row: these are content tokens, not monotonic revision counters.

Each successful add, edit, use, receive or removal from this workflow records
before/after values in `app_events` with event type `inventory_change`. Adjustments
also record the supplied reason. Stock and event commit together or both roll back.
An unchanged save does not add an event. Separate inventory rows may intentionally
share a name, so this is not automatic duplicate/lot consolidation. The legacy
CLI/database APIs retain their previous behavior and do not automatically gain
this workflow's audit or conflict checks.

These records are private, unencrypted local data. **Removal is not secure erasure**:
the old contents, including inventory notes, remain in application-event history
and prior backups. Full SQLite snapshots include this history; the older household
JSON export does not. Article knowledge-pack exports do not query these tables.
A dedicated history-browser and history-retention controls are not added here.

## Dashboard behavior

The graphical dashboard now reads inventory and household daily allowances in
one SQLite read transaction. It uses the existing 10% reserve convention. When
inputs are complete, quantity times amount-per-unit divided by the saved household
allowance reproduces the existing arithmetic. Edits from this Inventory panel
refresh the dashboard immediately. Refresh picks up changes from other windows.

The headline says **Set household** if no household/daily requirement is available,
and **Review inputs** rather than a numeric days estimate when positive water/food
stock lacks a per-unit amount or has a recorded date before today. Zero-quantity
rows do not trigger those resource warnings. The screen lists missing fields,
passed/upcoming dates and low-stock quantities. Invalid/nonfinite data causes
**Check data**, not a stale earlier estimate. A date alert means review is needed;
it is not a food-safety judgment or an automatic disposal instruction. A missing
or future date also does not establish that stock is usable or safe.

Household quick-add now exposes the saved daily water/calorie planning allowances
instead of hiding them. Its initial values are the existing application defaults,
not personalized intake recommendations. Existing household-profile editing is
not implemented in this slice. No medical, nutritional or hydration prescription
is supplied by this screen.

The raw CLI `water`, `food` and programmatic calculator APIs remain unchanged;
they do not gain these new graphical completeness/date labels. This distinction
is deliberate compatibility, not a claim that all interfaces now perform the
same input-quality assessment. Calculator-wide validation/eligibility alignment
remains follow-up work.

## Bounds and compatibility

The new editor/service rejects NaN, infinity, negative numbers and numeric values
above 1,000,000,000,000 (a software input bound, not a meaningful physical limit).
Names, units, locations, notes and reasons have explicit length bounds; dates use
YYYY-MM-DD. Basic legacy domain models and direct persistence APIs are unchanged.
An invalid legacy row can therefore still require correction before a dashboard
estimate is shown. All quantities are stored with the existing SQLite REAL format;
Decimal is used only for adjustment arithmetic, not as a new exact-value schema.

Database writes have a 250-millisecond SQLite lock wait, then report failure rather
than block behind another writer indefinitely. These small edits run on the GUI
thread; very slow filesystems or extremely large inventories can still take time.
This is not a benchmarked warehouse-scale inventory engine. No network request is
made, but user-chosen cloud/network storage has its own filesystem behavior.

Close the old application and back up its database before running updated source.
Existing downloaded ZIPs do not update themselves. This is a development-branch
code update, not a new signed installer, content pack or mobile application.

## Verification

Local tests use the exact existing `core/models.py` blob and synthetic SQLite
schemas matching the current inventory, household and event columns. They cover
parsing, input validation, exact units, conflict detection, concurrent consumption,
rollback after event failure, private change records, filters, estimates, missing
amounts/dates, and real Tk editing/adjusting/cancelling/removal/close guards.

Five additional full-checkout integration cases cover the actual application,
unchanged calculator and JSON-backup compatibility, full snapshot recovery of
stock/history, unchanged schema, and real desktop dashboard/close integration.
The existing Linux graphical and Windows recovery CI jobs are extended to include
the supplies workflow. Their observed results must be checked for the exact commit;
adding test commands alone is not a claim they passed.

Technical references consulted:
- SQLite transactions: https://www.sqlite.org/lang_transaction.html
- Python sqlite3 transactions and connection lifecycle: https://docs.python.org/3.13/library/sqlite3.html
