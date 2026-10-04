# Offline places and coordinates — 0.6.0

This is a cumulative, separately runnable FieldForge GPS source add-on. It is not
FieldForge.exe, a mobile build, a road-routing engine, or an installed world map
collection. No new real geographic data is bundled with this increment.

In 0.6, place search is also available in the combined GPS workspace. Selecting
a place pauses receiver following without disabling the live layer. See
[WORKSPACE.md](WORKSPACE.md) for the combined workflow.

## Start and use

Extract into a NEW folder. On Windows open `Start FieldForge Places.cmd`.
On Linux/macOS with Python and Tk, run `python3 -B -m fieldforge_gps.places_map_ui`.
Windows/macOS execution has not been verified in this development environment.

Click **Find places / coordinates…** in the local-map panel. To read a place file,
confirm both its permission/privacy checkbox and its WGS84 checkbox, then choose
**Open place CSV / GeoJSON…**. File selection is not saved between launches.
Nothing is downloaded, scanned, indexed on disk, or added to the household database.

The demo button opens six FICTIONAL records, including duplicate names, an accented
name, and date-line/polar examples. These are software fixtures, not destinations,
water sources, facilities, roads or claims that a place exists.

Type a name, alias, country/area, or region and press Search. Search is case- and
accent-insensitive, and matches all typed words against those fields. It is literal
text matching, not SQL, regular expressions, fuzzy matching, transliteration, or
an online geocoder. Non-Latin letters are retained; text entry/font support depends
on the operating system. At most 100 results are shown, alongside the full match
count. Narrow a query using region/country words. No result is selected for you.

Select a row and press **Show selected place on map**. Duplicate names and source
IDs remain separate records. The marker is a purple diamond labelled FILE PLACE,
not the orange GPX path or its historical selected point. Name matching does not
prove the selected place is the destination you intended. Coordinates do not
identify an exact entrance, street address, safe route or access permission.

Manual centering is independent of file reading: enter **latitude first**, then
**longitude**, in decimal degrees and press Show coordinate. The marker is labelled
MANUAL COORDINATE. DMS notation, hemisphere suffixes, scientific-notation text,
NaN/infinity, and out-of-range inputs are rejected, not guessed or clamped.
A +180 longitude is retained in the reference point but displayed at the equivalent
-180 map center. Zero is a valid coordinate, not a missing-data flag.

## File formats

UTF-8 (optional UTF-8 BOM), regular local files, at most 16 MiB and 50,000 records.
Archives, spreadsheets, shapefiles, URLs, network-share path syntax and other
coordinate systems are not supported. A file on an OS-mounted remote filesystem
cannot be distinguished reliably from an ordinary local path.

### CSV

Required header names: `name,latitude,longitude`.
Optional columns: `country,region,aliases,source_id,source`.
Column order is flexible; header case and surrounding whitespace are ignored.
Headers must be unique; unknown columns and mismatched row lengths are rejected.
Commas are the delimiter; quote fields that contain commas. Blank lines are ignored.
Every actual record needs a name and both coordinates. Decimal-degree strings only.
Aliases are separated with `|`, not commas; use at most 16 aliases.
The file source/template is plain text, not an Excel workbook.

Example (FICTIONAL):

```csv
name,latitude,longitude,country,region,aliases,source_id,source
Fictional Camp,32.0,0.0,Fictional Country,North,Demo Camp,fixture-1,FICTIONAL DATA
```

### GeoJSON

Supported subset: one FeatureCollection of named Point features, in WGS84
longitude/latitude. A coordinate position is `[longitude, latitude]`, with an
optional finite third elevation. Elevations are ignored and their count is shown.
Geometry coordinates are authoritative; similarly named latitude/longitude
properties do not override them. Non-Point, unnamed, null, invalid, or mixed
features cause whole-file rejection; the importer does not silently skip records.
This is not complete GeoJSON conformance or a general geospatial converter.

Properties: `name`, optional `country`, `region`, `aliases` (pipe-separated text or
string array), `source_id`, and `source`. A top-level `name` can supply a source
label. Feature `id` is a fallback source identifier. Unknown properties are ignored.

An adapter also accepts Natural Earth-style `name`/`NAME`, `nameascii`/`NAMEASCII`,
`namealt`/`NAMEALT`, `adm0name`/`ADM0NAME`, `adm1name`/`ADM1NAME`, and `ne_id`/`NE_ID`.
The adapter is tested with fictional records in that schema. This is NOT a claim
that the complete Natural Earth populated-places dataset was downloaded or tested.
Natural Earth feature geometry may differ from its latitude/longitude properties;
this importer deliberately uses geometry coordinates.

Modern GeoJSON omits `crs`. For the documented older Natural Earth export form,
this reader additionally accepts only:
`{"type":"name","properties":{"name":"urn:ogc:def:crs:OGC:1.3:CRS84"}}`.
Other explicit CRS declarations (including ambiguous legacy EPSG forms) and
feature/geometry CRS overrides are rejected; no reprojection or axis guessing.

Labels are plain text. URLs, HTML, file names or formulas in source attributes
are not followed, opened, evaluated or executed. Control/bidi formatting is
removed from displayed labels; original source bytes remain unchanged.
JSON duplicate keys and non-finite constants are rejected. JSON nesting is
limited to 16 levels and structural work to 1,000,000 punctuation tokens.
Names/context/IDs/individual aliases: at most 160 characters; source: 512;
collection name: 256; alias input text: 2,048; search: 160 and at most 12 words.

## Independence, cancellation, and privacy

New imports clear the old catalogue, search results, and FILE PLACE marker before
reading. Invalid imports do not leave old places pretending to be the new file.
Cancelling a file chooser, by contrast, leaves the existing catalogue unchanged.

A single place worker handles bounded reads/searches without Tk objects. There is
one replaceable queued job; cancellation and generation tokens reject stale work.
Changing query text immediately clears selectable old results; press Search again.
Long operations are bounded but not guaranteed to finish within a particular time,
especially on slow/removable filesystems. JSON decoding and sorting are not
interruptible at every instruction; cancellation is checked before publication.

Unchecking either place checkbox, clearing the catalogue, or closing the place
window cancels its work and clears its file data and FILE PLACE marker. This is
not secure memory erasure. Manual coordinates/markers are independent; clear the
map marker explicitly or close the map workspace to remove them. Closing the
finder clears its manual entry text, not an already selected manual map marker.

GPX permission, map permission, and place-file permission are independent. Clearing
places does not clear GPX history or close its map. Clearing GPX does not clear
places. Closing a map leaves the independently selected reference marker, which
may then lie outside the overview's current view. Place data is never written to
a receiver session, GPX recording, or household database.

File identity/size/timestamps are compared around reading/parsing, and an exact
SHA-256 is computed for the accepted bytes. The UI shows a short hash prefix; the
full fingerprint is available on the parsed catalogue object. These are consistency
checks, not signatures or protection against every malicious filesystem race.
A catalogue is an in-memory SNAPSHOT, not a live file watcher: reopen after changes.
Use trusted data and maintained Python/Tk versions. The parser is not a sandbox.

## Map and navigation limits

Points center the current map at its current zoom. No missing tile is downloaded,
no other zoom is substituted, and no street geometry is generated. Place markers
wait for the current local-map frame before drawing. They may sit on a visibly
missing/unreadable tile; a source point is independent of installed map coverage.

Latitude outside the Web Mercator extent is rejected on a local map rather than
moved to the edge. Close the local map to use the coarse overview for a polar point.
Latitude/longitude range checks cannot detect every swapped-axis error; trusted
source provenance and the user's coordinate-system confirmation remain necessary.

No live GPS map-follow, address lookup, road alternatives, turn-by-turn instructions,
current hazards, access checks, marine navigation, terrain or water-depth coverage.
Source region/country names are retained as source labels, not territorial judgments.

## Real-data acquisition status

Natural Earth's official terms, populated-place documentation and physical-layer
pages were read during development. Their licensing permits redistribution, but
attempts to obtain full new datasets into this execution environment failed.
No real index or world-reference pack is claimed as loaded. Only the previous
coarse land-outline data, previous FICTIONAL map, and new FICTIONAL places are here.
The source references are in `sources/PLACE-REFERENCES.json`; obtain and validate
appropriate licensed local data separately. The application has no downloader.

## Development

Runtime: Python 3.10+ with Tk. GPX reading separately requires Expat 2.6+; live serial
receiver input separately requires optional pySerial. Place import/search itself
uses only the standard library. No spreadsheet engine or online API key is needed.

```text
python -m pytest -q -ra -W error tests/gps_addon
python -m fieldforge_gps.places_map_ui
```

`verification/` contains this increment's actual tests and installed-package smoke
observations. `history/` contains previous reports, not fresh test execution.
