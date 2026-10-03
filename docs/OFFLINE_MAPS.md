# Offline raster maps — local MBTiles

The desktop **Maps** section opens an already-local map pack, renders its raster
tiles, and provides pan, zoom, coordinate centering and an optional saved-place
overlay. It has no network client, tile-server setting, GPS/location request,
geocoding, road routing, travel-time estimate or current-hazard data. No map data
is automatically downloaded, purchased or installed. A displayed map and a saved
meeting point are not verified safe travel guidance.

## Open a supported map

Choose **Maps → Open local map…**, select a trusted `.mbtiles` file and confirm
that you trust it and have permission to use it. Both the Maps tab and GPS workspace support a
specific MBTiles subset:

- PNG, JPEG or WebP raster imagery in ordinary `metadata` and `tiles` tables, using MBTiles'
  TMS rows and Web Mercator tile coordinates.
- A unique, non-partial index on `(zoom_level, tile_column, tile_row)` in that
  order, plus `name` and `format=png`, `jpg`, `jpeg` or `webp` metadata. The reader never builds an index
  or changes the supplied pack to make it compatible.
- Square 256- or 512-pixel images. A 512-pixel retina tile is subsampled to the same
  256-screen-pixel logical footprint. There is no extra detail invented from a
  lower zoom, no resampling fallback from another level and no remote fallback.
- Integer zoom levels between 0 and 22. Controls use levels actually present in
  the tiles table, not just claimed by metadata. A level's presence does NOT
  establish that every part of the viewport or declared region is covered.

PBF/vector tiles, animated tiles and normalized/view-based MBTiles layouts are
**not supported**. Those can be valid MBTiles formats; rejection means this reader
cannot display them, not that their files are corrupt. GPX, PDF maps and ordinary
image files are not MBTiles. The app does not convert these formats automatically.
Open ordinary map images through **Navigation → Open map image…**; see
[image formats and limits](GPS_WORKSPACE.md#mbtiles-and-image-files). Source users
install `.[maps]` for JPEG/WebP and map-image decoding; native PNG tiles continue
to work without Pillow. Use a fully exported, closed map copy; nonempty WAL/journal sidecars are refused.

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

## Verification and practice pack

Tests cover independent projection examples and round trips, TMS row reversal,
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

No application dependency, database schema or snapshot-format change is added.
No native Android/iOS viewer, browser map export, route planner, reviewed map
collection or local language model is delivered here. Update the application
source for this screen; content JSON cannot install it and old ZIPs do not
update automatically. Close the old app and back up its database first. Keep
external maps backed up separately before depending on them offline.
