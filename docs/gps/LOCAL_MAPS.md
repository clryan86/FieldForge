> Historical milestone notes. The workspace is now integrated into FieldForge.
> For current launch paths, PNG/JPEG/WebP MBTiles and image-file support, see
> [GPS workspace](../GPS_WORKSPACE.md). Older verification counts and standalone
> packaging boundaries below describe their original milestone.

# Saved trips over local maps — 0.4.0

This cumulative desktop source add-on joins the existing read-only GPX reviewer
to a new external PNG MBTiles layer. It does not connect the receiver to the map,
edit a GPX/map file, use a household database, or supply a route engine. A recorded
line is not proof of a traversable road, legal access, current safety, or accuracy.

## Workflow and independent permissions

Start with `Start FieldForge Local Maps.cmd` on a Python/Tk-equipped Windows
computer, or `python -B -m fieldforge_gps.local_map_ui` from the extracted folder.
Native Windows/macOS and physical mobile operation have not been tested here.
Existing Review and Trips → Review launch paths now use the cumulative viewer.
The underlying original `ReviewFrame` remains available as the coarse-only class.

The two inherited GPX confirmations govern private-history reading. The separate
map checkbox confirms that the selected local file is trusted and permitted for
use. Neither permission is saved. Opening the file chooser does not bypass the
second permission check after a modal dialog. Cancelling the chooser changes
nothing. Selecting a new map explicitly clears the old map before checking it;
a failed map-open does not erase the historical GPX document.

Map opening, tile reading, pan and zoom do not start receiver capture. Clearing
GPX history leaves an independently loaded map open. Closing the map preserves
GPX history. Revoking either permission clears only its respective workspace.
World overview closes the raster map and returns to the coarse bundled outline.
Map details / rights opens a read-only text window: no HTML, link following,
script execution, browser launch, clipboard action or export is implemented.

## Supported MBTiles subset

The implementation follows MBTiles 1.3's Web Mercator/TMS placement conventions,
while deliberately supporting only an indexed, ordinary-table PNG subset:

- Ordinary `metadata(name TEXT, value TEXT)` and
  `tiles(zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)`
  tables with that column ordering. Raster packs use supported image formats;
  vector packs use gzip-compressed Mapbox Vector Tile protobuf (`format=pbf`).
  Views/virtual tables and extra columns are
  not accepted by this first reader. Other valid MBTiles layouts can be rejected.
- A unique non-partial BINARY-collated index whose key columns are precisely
  `(zoom_level, tile_column, tile_row)`. The app never repairs or builds an index.
- Required `name` and a supported image format or `format=pbf`. An explicitly
  supplied `scheme` must be TMS.
  Metadata is bounded to 128 entries, 128 bytes per key and 16 KiB per value;
  duplicate keys, non-text fields, control-bearing keys and oversized fields fail.
- Zoom levels actually observed between 0 and 22. Metadata `minzoom`/`maxzoom`
  does not invent levels. An observed level is not evidence of full coverage.
- Square raster tiles, 256 or 512 pixels. The latter are subsampled to a
  256-pixel logical footprint. PBF vector tiles receive a basic preview style
  with limited labels from embedded point-feature names. Publisher styles, fonts,
  sprites, filters, expressions and label-placement rules are not applied.
  There is no lower/higher-zoom substitution or resampling beyond retina-tile
  reduction.
- SQLite rollback-mode header and no nonempty WAL/journal/SHM sidecars. Use a
  completely exported, closed copy on a local drive. URL/UNC-style inputs are
  rejected. Mapped/mounted network filesystems cannot be reliably identified.

A valid declared center and observed zoom may supply Pack start. Otherwise, the
center of an observed initial tile is used, with an explicit explanation. Neither
is an inferred current location. Bounds, dates, descriptions, attribution and
license statements remain unverified pack-supplied text. Missing information is
not filled with claims of public-domain status, freshness or complete coverage.
There is no full-pack integrity scan, authentication or license verification.

## Projection, overlays and missing data

The raster view uses Web Mercator, not the inherited equirectangular coastline
projection. The same coordinate conversion aligns historical points with map
tiles. Coordinates beyond approximately ±85.05112878° latitude are not moved to
the map edge. They remain inspectable as source points, are counted as excluded
from the raster view, and break display runs. The full track is split on polar
points BEFORE preview decimation, preventing a hidden polar point from being
bridged by a simplified line. Use the world overview to review those latitudes.

File-defined segments remain separate. The raster overlay is capped at 8,000
preview samples and reports full-file counts, display-run counts, simplification
and full-track polar exclusions. A display run may end at a projection exclusion,
not only at a GPX segment boundary. Circles and squares mark display-run starts
and ends; unshown runs may be omitted when the preview budget is exhausted. Full
accepted source points remain available in the point inspector. Unknown gaps not
represented in the original GPX still cannot be reconstructed.

Date-line crossings take the shorter longitude arc and are clipped at viewport
edges. The map repeats horizontally when needed; polar rows never repeat.
Historical markers use the nearest world copy; the polyline may appear in more
than one visible world copy at very low zoom. Dense connected preview lines are
batched into clipped paths, not one canvas object per source edge.

Displayed tiles, missing tiles, unreadable/unsupported PNG tiles and cells outside
projection have distinct states. Counts describe visible cells, including repeated
world copies, not unique installed files or global coverage. During a new view
request, previous imagery is removed instead of reused under new coordinates.
No partial frame is accepted. A valid tile's appearance can itself be blank or
inaccurate; this reader cannot interpret whether its depicted geography is useful.

## File/thread safeguards and limits

SQLite is opened with URI `mode=ro`, query-only mode, trusted schema disabled,
in-memory temporary storage and a small page cache. Each viewport is read in one
transaction. Ordinary file identity/size/modification metadata is checked before
and after reads. Changed files fail; close and reopen to explicitly accept a new
version. This is NOT a whole-file checksum, signature, exclusive lock or defense
against malicious path races/restored timestamps. Stationary cached imagery is
not continuously watched: changes are checked on the next tile read.

The map reader has one worker plus one replaceable pending request. Each request
has cancellation and a generation token. Late results cannot replace a newer
view or reappear after opt-out, another file, or window close. Worker arguments
contain no Tk objects; Tk PNG decoding and all widget mutation stay on the UI
thread. A closed worker is asked to stop, not forcibly terminated during OS I/O.

Limits are 16 GiB per pack, 2 MiB compressed bytes per PNG, 32 MiB unique compressed
tile bytes per frame, 96 visible cells, and a 2560 × 1600 maximum map canvas. Map
query work uses a four-second monotonic deadline checked every 1,000 SQLite VM
instructions, a 20-million-instruction cap, and a 250 ms lock timeout. These are
implementation guards, not measured support for a 16 GiB pack or guaranteed
latency on damaged/removable storage. File I/O and Tk decoding are not forcibly
interrupted by the SQL progress handler. Decoded images need additional memory.

PNG preflight checks bounded size, signature, IHDR dimensions/encoding and header
CRC. Tk performs actual image decoding; body errors become unreadable cells.
This is not a complete PNG validator, malware scanner or hostile-file sandbox.
Use trusted files and maintained Python/SQLite/Tk software. The script does not
alter security settings, download dependencies, or obtain maps from tile servers.

Status and preview-message areas reserve fixed height. Their text must not resize
the canvas and trigger an alternating read/redraw loop. Regression tests exercise
that condition and gracefully reject oversized viewports, including during drag.

## Included data and integration boundary

`FICTIONAL-MAP.mbtiles` is an original test grid with deliberately missing tiles,
not a geographic, street, terrain or nautical dataset. Four levels are present:
0, 2, 4 and 5. `tools/build_fictional_map.py` rebuilds it into a NEW output file
using development-only Pillow; the runtime does not invoke the generator.
`FICTIONAL-REVIEW.gpx` remains an artificial, non-navigable test journey.

The old coarse land outline is retained unchanged, with unknown original data
vintage as documented in `sources/OVERVIEW-PROVENANCE.json`. No additional real
street/city/country/water/terrain coverage or turn-by-turn guidance is delivered.
No main FieldForge modules are vendored, no database schema is changed, and no
newest regional-index interoperability claim is made. This subset was compared
with the upstream documentation at commit
`8d8a739d4357d50b27697067f82cfbe1f1d8347e`; its complete source was not available for
local integration regression. Reading that documentation is not compatibility
verification. The five inherited optional main-program checks remain skipped.

## Reproduce

From the source folder with pytest, Tk and a display:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 xvfb-run -a -s '-screen 0 1440x1200x24' \
  python -m pytest -q -ra -W error tests/gps_addon
```

The portable wheel can be installed into a NEW empty directory without any index
or dependency access. The independent installed-package smoke script is supplied
under `verification/`; it uses trusted temporary fixtures and development-only
Pillow for a screenshot. See `VERIFICATION.txt` for exact observed outcomes and
limitations. Repeated runs are not additional unique tests.

Technical references consulted October 2, 2026:
- https://github.com/mapbox/mbtiles-spec/blob/master/1.3/spec.md
- https://sqlite.org/uri.html
- https://sqlite.org/pragma.html#pragma_query_only
- https://sqlite.org/pragma.html#pragma_trusted_schema
- https://docs.python.org/3/library/sqlite3.html
