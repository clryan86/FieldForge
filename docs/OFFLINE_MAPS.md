# Offline maps — included atlas and local raster/vector MBTiles

> This guide describes tested local integration `fe70c8b`. Publication is pending;
> see [map integration status](MAP_INTEGRATION_STATUS.md).

The desktop **Maps** screen opens the included atlas or an already-local map,
renders raster tiles or a basic vector preview, and provides pan, zoom,
coordinate centering and optional place/route overlays. It makes no network or
GPS request and performs no address lookup or route calculation. Separate online
tools can prepare maps and routes when explicitly connected.

## Included overview and town search

Choose **Maps → Included U.S. atlas…** to open the application resource without
a manual import or download. Its **615 tiles** provide a world overview at
zooms 0–3 and U.S./territory overview coverage at zooms 4–6. Counts by zoom are
1, 4, 16, 64, 62, 143 and 325. Region choices include the lower 48, Alaska,
Hawaii, Puerto Rico / U.S. Virgin Islands, Guam / Northern Mariana Islands,
and American Samoa.

Choose **Find included U.S. towns…**, search by town or state, select a result,
then **Show selected town on included atlas**. This opens the atlas with a
temporary marker; **Clear town marker** removes it. No private waypoint is
created. An empty query browses up to 100 of the **777 selected towns**;
narrow the query to find other matches.

Natural Earth's 1:50 million layers show generalized land, state outlines,
selected city labels, rivers and lakes. The separate 1:10 million populated-places
selection supplies the town catalogue. These resources do not include every
settlement, every address, a full U.S. street database, terrain elevations,
current conditions, safe-water assessments or a routing graph. Small islands
and features may be omitted.

The GPS workspace has the same **Included U.S. atlas…** and a separate
**Find places / coordinates… → Included U.S. towns** action. A selected point
centers its current map or coarse outline and pauses receiver following.
See [GPS workspace](GPS_WORKSPACE.md) and [bundled atlas](BUNDLED_ATLAS.md).

## Open a supported external map

Choose **Maps → Open local map…**, select a trusted `.mbtiles` file and confirm
permission to use it. Both map surfaces support these bounded layouts:

- **Flat:** ordinary `metadata(name TEXT, value TEXT)` and
  `tiles(zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)`
  tables with the supported column layout.
- **Normalized:** ordinary `metadata`, `map` and `images` tables. The map table
  has integer tile coordinates and `tile_id`; images has the same declared
  tile-ID type and BLOB `tile_data`. Supported ID types are TEXT, INTEGER and
  BLOB. A `tiles` view may exist, but the reader never executes it: it uses
  a fixed indexed join over the physical tables. Other view-only layouts,
  virtual tables and generated/hidden columns remain unsupported.
- Unique, non-partial, BINARY-collated coordinate indexes must already exist.
  Normalized images also need a unique `tile_id` index. No index or conversion
  is written. Absent coordinates are missing tiles; dangling image references
  are bad data.
- Tile contents may be PNG, JPEG (`format=jpg` or `jpeg`), WebP, or gzip-compressed
  Mapbox Vector Tile data (`format=pbf`). Metadata requires `name` and `format`,
  with up to 128 entries and 16 KiB per UTF-8 value.
- Raster tiles must be square, 256 or 512 pixels, using Web Mercator and TMS rows.
  A 512-pixel tile occupies the same 256-screen-pixel footprint. Animated tiles
  are unsupported. Observed integer zooms run from 0 to 22; no alternate-zoom
  or remote fallback invents missing detail.
- MVT/PBF tiles receive a basic preview for common land, water, buildings, roads,
  boundaries, rail and points, with bounded embedded point/line/area names.
  Publisher styles, filters, fonts, sprites, glyphs and advanced symbol placement
  are not applied. These vector tiles are different from raw OSM `.osm.pbf`
  source snapshots.

The portal's MBTiles **publisher remains flat-only**. A normalized file that opens
locally is not automatically eligible for portal publication. GPX, PDF maps,
ordinary images and prepared `.ffmap` indexes are separate formats; the app
does not automatically convert them into MBTiles.

Open ordinary map images through **Navigation → Open map image…**; see
[image formats and limits](GPS_WORKSPACE.md#mbtiles-and-image-files). Source users
install `.[maps]` for JPEG/WebP and map-image decoding; native PNG tiles continue
to work without Pillow. Use a fully exported, closed rollback-mode map copy;
WAL-mode headers and nonempty WAL, journal, or shared-memory sidecars are refused.

The map file is read in place, not copied into SQLite or registered in a persistent
map catalog. Closing the map or application forgets its file selection and view.
**Full FieldForge database backups do not include external map packs.** Keep a
separate copy of the pack, source documentation and relevant license files.
Opening a map does not import locations, write any waypoint or modify the file.
A removable drive or moved file must remain available while reading the map.

## Move around and interpret coverage

Drag the map and release to request new tiles. Use +/−, the wheel or the zoom
selector to change to an available level. Arrow keys pan when the canvas has
keyboard focus. **Pack start** returns to a valid declared center/zoom, or the
center of an observed initial tile if the declaration is absent or invalid.
Invalid-center fallback is recorded under **Map details / rights…**. This is not
an inferred current location or a guarantee the initial region is useful.

Signed decimal center coordinates use latitude first, then longitude. World
imagery repeats horizontally across the date line; northern/southern projection
limits are not repeated. The Web Mercator extent stops at approximately
±85.05112878° latitude. Polar coordinates and polar saved places are not silently
moved to the edge; centering is rejected and out-of-extent markers are counted
as excluded. North is up; there is no rotation or magnetic-compass correction.
The pointer reports a calculated map position, not a GPS or surveyed observation.

**Tile not installed**, **Unreadable/unsupported tile**, and **Outside projection**
are different visible states. Missing imagery is never drawn as an empty land
area or described as safe. The status reports counts for visible cells, which
may include repeated world copies at low zoom. Fully displayed cells are still
not proof of map freshness, positional accuracy, access rights or safe roads.
A corrupt or changed map file clears the frame instead of leaving an old map
under new coordinate labels. A new failed file-open also removes the prior map.

Only a bounded viewport is loaded: at most 2560×1600 screen pixels and 96 visible
cells, at most 2 MiB source bytes per tile, 32 MiB of unique source/display-PNG
tile buffers per frame (whichever is larger for each tile) and 16 GiB per external pack. Larger input or excessive
visible data fails with an explanation. These bounds are implementation limits,
not a benchmark for all storage hardware or a claim that a 16 GiB pack was tested.
Decoded images and the running application need additional memory.

## Source information and personal places

Attribution is displayed as pack-supplied text. **Map details / rights…** shows
all accepted metadata, including full attribution when the compact label is
shortened. HTML and source URLs stay inert text, not executed or fetched links.
Missing attribution/rights are not replaced with a claim of public-domain content.
Metadata, bounds and dates may be inaccurate or stale; no source endorsement or
license verification is performed. This reader does not obtain permission for
bulk downloading from online tile services or redistribute third-party maps.

**Show saved places (private)** is off by default and resets when another map is
opened. Enabling it reads only existing waypoint IDs, names and coordinates,
never private waypoint notes, household profiles or other personal tables. Names
and coordinates themselves can be sensitive: the overlay displays them on your
screen, but does not write them into a map, exported image or shared artifact.
Turn it off before screen sharing. No overlay is exported by this milestone.

Choose a saved place in the dropdown and **Center on chosen place** to use its
captured coordinates. Refresh to load subsequent edits from Places. Markers are
snapshots of existing records, not device tracking. Invalid place data clears
the overlay with an error; it does not block otherwise readable map imagery.
Locations not in the current viewport remain in the chooser. Multiple nearby
labels may overlap; no clustering, hidden route, history trail or geofence is
implemented. Place records continue to follow their existing database backup
and GPX-sharing rules, separate from the external imagery.

## Read-only and cancellation boundaries

Map SQLite connections use read-only URI mode, query-only mode and disabled
trusted schema. Metadata counts/sizes, table shapes, index shape, raster dimensions
and compressed sizes are bounded. Tile preflight does not completely validate
PNG content; Tk performs PNG decoding and decode failures become marked cells.
JPEG/WebP tiles are decoded by Pillow in the worker, checked against the declared
format/dimensions, and converted to metadata-free PNG display buffers.
Only trusted files should be opened with a maintained Python/SQLite/Tk build.
This is not a malware scanner, content sanitizer or hostile-file security sandbox.

Each frame reads within one map-database transaction. File identity, size and
modification metadata are compared around reads to reject ordinary changed files.
This is not a full-file checksum, signature, immutable history, exclusive lock or
a defense against a malicious actor who can race paths or restore timestamps.
Previously viewed tile bytes are not silently reused after a changed-file error.
Close and reopen the intended pack to explicitly accept a different file version.

SQLite work has a progress-handler deadline and 250 ms lock wait. Cancellation
signals stop obsolete queries and generation tokens prevent their late results
from appearing after a new file, pan, zoom, opt-out or close. Regular filesystem
I/O and image decoding are not forcibly interrupted or guaranteed to finish within
that deadline. Workers read data and decode non-PNG tiles; Tk PNG decoding/drawing is on the main thread.
There is no mid-read database write to wait for when closing the application.
Existing guards still protect unrelated unsaved editors and active write jobs.

## Prepared regional `.ffmap` indexes

The Maps tab also has a separate **Prepared regional map…** viewer for FieldForge
`.ffmap` SQLite indexes. These are not MBTiles. Choose **Import package ZIP…**
to validate a regional ZIP and copy only its single `map.ffmap` index; the
archive and bundled source PBF remain unchanged. You may also extract the archive
yourself and open `map.ffmap` directly. **Prepare PBF…** builds a new index from
a local OSM PBF snapshot without replacing the source. The viewer searches
indexed names and features locally and limits how many features it loads for a
viewport; zoom in when it reports that the view is limited. The available Wave
5 indexes cover Kansas, Nebraska, North Dakota, and South Dakota only, not all
U.S. states. ZIPs over 2 GiB and indexes over 4 GiB are rejected.

These indexes are for display and local feature search. They do not contain a
prepared routing graph, support turn-by-turn navigation, or verify road access,
freshness, safety, or completeness. The current portal does not distribute
`.ffmap` indexes or extract ZIP packages. See the [regional data
plan](GLOBAL_MAP_DATA_PLAN.md) for provenance and acquisition gaps.

## Saved routes and online preparation

The separate **Online Maps** tools connect to an operator-configured portal for
address lookup, map downloads and driving-route alternatives. Completed downloads
are verified against catalog size and checksum. Saved or imported online-planned
routes can be reopened for directions, drawn over a local map and exported as GPX
after disconnecting. This does not calculate new offline routes or reroute around
closures. See [Online map portal](ONLINE_MAP_PORTAL.md).

## Verification and practice resources

Current headless/installed-package results and pending GUI/Windows work are listed
in [map integration status](MAP_INTEGRATION_STATUS.md). Existing coverage includes
independent projection examples and round trips, TMS row reversal,
date-line wrapping, polar exclusion, no lower-zoom substitution, source metadata,
read-only files, required indexes, invalid PNG headers/dimensions, actual Tk PNG
decoding, missing/corrupt cells, budgets, changed files, SQL cancellation/deadlines,
private-note-column exclusion, pan/zoom/center, consent, stale callbacks, overlay
opt-in/opt-out, compact geometry and normal desktop close during a read. Full
integration checks preserve waypoint/knowledge backups while proving external
map imagery is not included. Existing regression and browser gates remain.

The downloadable **FieldForge-Map-Practice.mbtiles** is original synthetic grid
imagery for testing the software, **not a geographic map**. It contains no actual
roads, coastlines, buildings or safe destinations. Its deliberate missing tile
lets you exercise the coverage warning. The practice file and screenshots do
not use the user's coordinates, private notes or third-party tile downloads.
Nothing is seeded into the user's database by opening that sample.

Technical references consulted for implementation:
- MBTiles 1.3 schema and TMS row convention:
  https://github.com/mapbox/mbtiles-spec/blob/master/1.3/spec.md
- Web Mercator / XYZ projection and tile geometry:
  https://wiki.openstreetmap.org/wiki/Slippy_map_tilenames
- Python Tkinter image handling:
  https://docs.python.org/3.10/library/tkinter.html
- Python SQLite read-only URI, transactions and progress handlers:
  https://docs.python.org/3.13/library/sqlite3.html

No native Android/iOS map application or new offline routing engine is delivered
by this integration. Receive these features through an explicitly identified
application build; content JSON cannot install source changes and old ZIPs do
not update automatically. Source/data publication and GUI/Windows execution
remain pending. Keep external maps, source documentation and rights files
backed up separately from the household database.
