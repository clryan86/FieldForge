# Offline Places & Bearings

The desktop **Places** tab brings the existing waypoint records into an editable
workspace. Add a name/alias, signed latitude, signed longitude, type and optional
private notes. Saved meeting points are user records, **not verified safe
locations**. Nothing is automatically seeded from profiles, messages or devices.
Manual entry and saved-place search work offline. **Find address online…** in
the editor opens the optional [map portal](ONLINE_MAP_PORTAL.md): connect, enter
a search, select a match and fill the fields for review before saving. This does
not request your current location or notify another person. The Places tab's
distance/bearing estimates remain separate from online driving-route planning.

## Enter and edit places

Use **WGS 84 decimal degrees**, with latitude first. North/east are positive;
south/west are negative. A blank is unknown, not zero. The editor does not guess
coordinate order or accept degrees/minutes/seconds, direction letters, expressions,
commas or exponent notation. Accepted coordinate numbers must be finite and in
range: latitude -90 through +90, longitude -180 through +180. These validation
checks do not establish that an entered location or its datum is correct.

The existing `waypoints` table is used without a migration. Previous CLI-created
waypoints remain available, and new records remain visible to that CLI. Unknown
schema shapes and invalid legacy records produce errors instead of being reset
or silently hidden. New names are trimmed (up to 200 characters), types up to 80,
and notes up to 4,000; supported note whitespace is retained. The workspace is
bounded to 2,000 saved places. No per-user profiles or automatic events containing
coordinates are added. Manual creation can intentionally use a duplicate name;
GPX intake applies the stricter conflict policy below.

Each edit/remove compares the loaded full-row fingerprint inside a write
transaction. Another window, including the older CLI or an external SQL editor,
changing that row causes a conflict rather than a silent overwrite. An unchanged
save does not write. This detects differences in current content, not an immutable
history; changing a row away and back to exactly the same contents is not tracked.
No protection against a malicious local administrator is claimed.

Search is literal, case-insensitive matching in names and types, with pages of
50 records. It is not a search of private notes or a map. Select one place to
edit/view it; use Ctrl/Shift to select several places for GPX export. Deleting a
place requires confirmation and removes its note from the active table, not
external files, old backups or SQLite free-page remnants. It is not secure erasure.
A compact-window section selector makes all desktop tabs reachable when their
labels do not fit the window width.

## Point-to-point estimates

Select a place and **Use selected place as start**, select another and **Use
selected place as destination**, then **Calculate from saved coordinates**.
Both endpoints are read in one SQLite snapshot. The result identifies the saved
coordinates used and the device-UTC calculation time. Later edits do not update
a displayed result automatically: refresh and recalculate.

The great-circle calculation uses a sphere with radius 6,371,008.8 m, matching
the existing helper's radius. It is not an ellipsoidal survey calculation, road
length, walking distance, travel time or safe route. Terrain, barriers, rights of
access, bridge conditions, current hazards and evacuation instructions are not
considered. A straight connection between two points is not travel guidance.

The angle is the **initial TRUE bearing**, clockwise from true north, not a
magnetic compass reading or a constant bearing along the entire path. No magnetic
declination model or correction is included. Coincident/extremely close points,
antipodal/nearly antipodal points and an origin at/extremely near a geographic
pole return an explicit unavailable-bearing explanation, not an invented 0°.
Small numerical tolerance zones prevent unstable results at those degeneracies.
Printed decimal digits are calculation output, not a claim of coordinate accuracy.
Private place notes are excluded from the calculation result.

## GPX 1.1 waypoint import

**Import GPX…** opens a separate preview. Choose a trusted UTF-8 `.gpx` file with
GPX 1.1's namespace, creator attribute and waypoint elements. This is a deliberately
limited waypoint importer, not a full GPX validator or general route/track reader.
Files with routes or tracks are rejected in their entirety rather than silently
importing only some locations. GPX 1.0 and UTF-16/other declared encodings are not
supported. Maximum input is 1 MiB and 200 waypoints. XML nesting/element counts
are bounded; DTDs, entity declarations, external entities and processing
instructions are rejected. No XML schemas, URLs or external resources are fetched.
Use trusted files and a maintained Python/Expat installation; this is not a
malicious-file sandbox or a memory/timing guarantee on every interpreter.

Fields retained are latitude, longitude, name, type and description. Descriptions
become private place notes. Missing names get a visible generated name such as
`Imported waypoint 1`; the preview reports how many were assigned. Optional
metadata, elevation, time, comments, extensions and other supported-but-unused
GPX elements are reported as omitted, **not retained in the database**. Unknown
waypoint elements and nested markup in the retained text fields are rejected.
Keep the original GPX outside FieldForge if those other fields matter.

Review every point, action and omission, then acknowledge the storage notice.
Names are compared case-insensitively after trimming. A name with identical
coordinates, type and note is an exact duplicate and skipped; a same-name record
with different details is a conflict. Any conflict blocks the whole import. This
also applies to conflicting names within the input itself. There is no automatic
renaming, merge or replacement of existing notes. Reconcile the file/records
explicitly instead of guessing which location the name was meant to identify.

The preview captures input content and the waypoint collection's version. The
commit rechecks the collection under a writer lock. A change to any waypoint
between preview and commit requires **Recheck captured import**; unrelated
household/article changes do not invalidate it. All new places commit together
or roll back, including failure of a later insertion. Exact duplicate-only
imports are no-ops. Rechecking uses the captured GPX, not a reread of a changed
external file; choose the file again to capture a different version.

## GPX export and privacy

**Export selected…** captures precisely the selected saved records. It does not
export hidden/unselected records or change them as filters change. Private notes
are **excluded by default**, independently of article-pack note settings. Turning
on **Include private place notes** clears the old preview/confirmation and requires
a new preview. Changes to saved records after capture do not change that copy.

Names, types and precise coordinates are included even when notes are omitted.
The export confirmation makes that disclosure explicit. A GPX is unencrypted,
may be importable by other mapping software, and is not a secure way to share
private meeting places. No program opens, sends or uploads the result automatically.
No specific GPS device/app compatibility is claimed beyond the GPX subset and
round-trip tests; external software may interpret fields differently.

GPX 1.1 requires longitudes below +180, so export represents a stored +180 as
its equivalent -180 meridian without changing the database. Finite floats are
written as round-trip decimal text, without exponent notation or extra rounding.
Source strings are XML-escaped; opted-in carriage returns use numeric references
to avoid XML newline normalization. No executable markup is taken from notes.

Export creates a **new** `.gpx` file and refuses existing files or symlinks.
Ordinary write errors remove only the partial file created by the operation.
There is no hard-link requirement. Publication is not atomic: a forced exit or
power loss may leave a partial new file. Input/output capture limits and the
250 ms database lock wait are not hard deadlines on a stalled filesystem.

## Existing backups and application boundaries

Full SQLite snapshots already include waypoints and notes; recovery counts
already report waypoints. Article JSON knowledge packs, Field Binder and Ask
Library do not export/index waypoint records. The old household-only JSON backup
is still partial and is not a waypoint backup. GPX is an interchange subset, not
an application backup, revision archive or recovery copy of every field/table.

A place editor or GPX dialog holds the normal-close and full-backup guard until
it is dismissed. Edits/GPX imports do not auto-save merely because a dialog opens.
GPX capture/preview/write operations run off the Tk thread; normal closing is
blocked during writes. Read-only preview cancellation discards late results.
Small manual edits and calculations use the main thread's existing short SQLite
transaction pattern. Coordinates/notes/database backups remain unencrypted.

## Verification scope and technical references

Tests independently check cardinal distances/bearings, date-line crossings,
undefined bearings, consistent endpoint snapshots, strict input validation,
legacy compatibility, edit conflicts, GPX XML bounds/escaping/field omissions,
atomic imports/deduplication/capacity, new-file protection, exact selected exports,
private notes, real Tk workflows and full recovery/application integration.
Examples and screenshots use fictional coordinate exercises, not user addresses
or proposed real destinations. The complete baseline source is available locally;
local and CI outcomes are recorded against the exact published commit.

Technical references consulted:
- Topografix GPX 1.1 schema (WGS 84, waypoint fields and longitude range):
  https://www.topografix.com/GPX/1/1/
- NOAA/NCEI magnetic declination (true versus magnetic north):
  https://www.ncei.noaa.gov/products/magnetic-declination
- Python XML security considerations:
  https://docs.python.org/3/library/xml.html

Updated source is required for the Places screen. Existing downloaded ZIPs do not
auto-update. Close the old app and back up the database before using a new build.
No new maps, reviewed survival corpus, native mobile client, local language model
or signed installer is added by this milestone.
