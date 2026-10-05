# Hosted portal preview

The owner preview is live at **[FieldForge portal](https://fieldforge-portal.chris1986ryan.chatgpt.site)**.
It is private to the site owner. It was published successfully on October 5, 2026.

This is a static portal preview, not a public launch of the Python chat server.
The portal preserves the current map, route, library, tier and resource layout.
It adds a searchable U.S. source-region list and a Commons gallery with actual
local-test screenshots of rooms, private inbox, accounts, owner announcements
and saved-message search. The screenshots use test participants.

## What is and is not live

External provider links and the device-only skill-label preview work here.
The connection confirmation enables external source links; it does not disable
the device's internet or turn the website into an offline application.

Chat, sign-in, account/profile storage, owner authentication, geocoding, routing,
map hosting, knowledge-package hosting and billing are **not** connected to this
website. The local application remains separate. No account database,
credentials or third-party map collection was uploaded. No E2EE or screenshot
prevention is claimed. Provider descriptions are inherited from the portal;
this publication does not re-verify prices, licensing or external availability.

## Rebuild without forking the application

The original application portal is unchanged. Export it from a FieldForge
checkout with:

```sh
python tools/build_hosted_preview.py --output /tmp/fieldforge-preview --revision 6ba72816678b9271f190b34d818faa4e89d0eed7
node --check /tmp/fieldforge-preview/preview.js
```

Use the actual source commit when refreshing. The exporter deliberately fails
when expected HTML anchors change. Review and update its transformations; do
not silently publish the application API script on static hosting.

Required input: `fieldforge/online/portal.html` and the five screenshots named
in the exporter under `docs/images/`. The output contains only static HTML,
CSS, JavaScript and those images. The normal Python server is not exposed.

## Maintain this same Site

- Project: `appgprj_6ac3e4ba2c148191951eb50825d1dab4`.
- Initial Site source commit: `c6a9d1a687845d18649ccbebb262636af2b29c08`.
- Portal source snapshot: `6ba72816678b9271f190b34d818faa4e89d0eed7`.
- Site manifest: `static.directory = dist`.

Open the existing Site, refresh its source snapshot and export, then publish an
updated version with the same project identity and audience. Do not register a
replacement Site. Its own source repository retains the deployment source and
manifest; this GitHub repository retains the repeatable exporter and handoff.

Validation performed for this publication: exporter success, JavaScript syntax,
all local page/image links and fragment targets, unique element IDs, absence of
application API handlers, image inspection, and successful hosted deployment.
Live provider calls and multi-user messaging were not tested on this static Site.

## Preparation desk update — October 5, 2026

The portal now opens on two working, browser-local tools:

- **Plan map downloads:** select among 53 U.S. PBF source regions, search or show
  selected regions, compare estimated size to a decimal-GB budget, and estimate
  transfer time from an entered Mbps speed. Save/reopen a source-plan JSON file,
  or explicitly opt into device storage. A source plan is not a desktop map
  download manifest and contains no map bytes. Provider size estimates are the
  original October 4 snapshot; preparation requires extra disk space.
- **Inspect a GPX file:** choose or drop a file, draw its coordinate trace, count
  segments/points/waypoints, measure segment-aware great-circle length, and
  export explicit waypoints using the desktop place CSV columns. Files never
  upload and their coordinates are never put in browser storage. Limits: 2 MiB,
  25,000 total points and 1,000 waypoints. The preview table shows the first 100;
  CSV exports every waypoint, rounded to seven decimal places. Track geometry
  is not a basemap, driving route or route-safety assessment.

`tools/portal_preview/` contains the desk HTML, CSS, ES modules and regression
checks. The exporter now needs this sibling directory. To verify the logic:

```sh
node --test tools/portal_preview/desk-core.test.mjs
```

Ten focused checks passed for estimates, plan validation, coordinate limits,
segment boundaries, date-line crossings, polar/single-point plots, safe CSV
output, XML entity rejection, namespace traversal and point limits. XML traversal
checks use injected DOM fixtures; they do not claim browser rendering coverage.
The export was also checked for JavaScript syntax, valid local links/anchors,
matching control IDs, all 53 source regions and absence of network calls in the
preparation modules. No additional live chat or sign-in was enabled by this update.

## Route exploration update — October 5, 2026

The GPX inspector now supports bounded 1–8× zoom and pan, point selection from
the coordinate plot, a keyboard-operable point slider and previous/next buttons.
An all-waypoint picker reaches every waypoint even when the table is limited to
its first 100 rows. A selected point can be exported as the existing FieldForge
place CSV format. Metric/imperial display changes do not change coordinates.

Optional GPX elevation is read from the file only. A linked profile shows recorded
heights against cumulative segment-aware distance. Missing, malformed or duplicate
elevation records remain missing; no provider fills them in. Separate track
segments and missing-height runs are never joined. Raw ascent/descent sum only
adjacent valid heights within the same segment and are not corrected for GPS
noise. A lone valid height is plotted but cannot supply an ascent/descent estimate.
No terrain safety, driving route or reliable vertical accuracy is asserted.

Selecting a profile point updates the coordinate marker and readout. Repeated
route distances are resolved by the clicked chart position when possible; the
slider remains available for every route point. The chart labels use HTML text
to stay readable at narrow widths. Clearing or replacing a file removes the
profile, selected coordinates, waypoint options, geometry and export state.
No GPX coordinates or elevations are persisted or uploaded.

The focused Node suite now passes **17 checks**. New coverage includes genuine
zero elevation, malformed and missing heights, segment/gap boundaries, flat and
stationary profiles, repeated distances, chart point selection and bounded zoom.
Module syntax, imports, HTML control IDs and local links/anchors were also checked.
These are calculation and structure checks, not a claim of browser visual QA.
Live chat, sign-in and hosted route/map providers remain unchanged and unavailable
on this private preview.


## Local map-image viewer — October 5, 2026

The hosted preparation desk now has a third tool, **Open a map image**:

- PNG, JPEG and still WebP images are read and decoded in the browser. Files
  are limited to 32 MiB, 24 megapixels and 32,768 pixels per side. Signature,
  dimension and container checks run before native image decoding; animated
  PNG/WebP files are rejected. No files or coordinates are uploaded.
- Fit, bounded 1–16× zoom, directional pan, click selection and keyboard pixel
  selection work without geographic calibration.
- Optional full-image, north-up bounds support a latitude/longitude grid
  (EPSG:4326) or Web Mercator (EPSG:3857), including date-line crossing. Bounds
  must cover the full displayed, browser-oriented image. Pixel-center WGS 84
  coordinates can be exported as a place-catalog CSV with image provenance.
- Editing the bounds immediately disables coordinate calculations until Apply
  bounds. Bounds are user supplied, not independently verified. Borders,
  legends, rotated maps and other projections invalidate this simple method.
- A separate image-bounds JSON file can be explicitly saved and reopened. SHA-256
  of the original image bytes and the displayed dimensions must match; a
  mismatched file is rejected without replacing existing valid bounds.
- Images and bounds remain in tab memory only. Closing/clearing discards them;
  stale reads and decodes cannot repopulate cleared state. Decoded bitmaps are
  closed and image reads/decodes serialized to limit memory allocation.

This tool does not read TIFF/GeoTIFF, SVG, PDF, GIF, BMP or MBTiles, extract
georeferencing/GPS tags, fetch a basemap, or supply routing. No map dataset was
acquired or bundled. Canvas and ImageBitmap support are required; saved bounds
also require secure SHA-256 support. The page is not installed/cached for later
offline reopening. Live chat, sign-in and application hosting remain separate
unfinished deployment work.

Validation: `node --test tools/portal_preview/*.test.mjs` passes **29 tests**.
New coverage exercises format metadata, limits, date-line and Mercator transforms,
screen/pixel transforms, calibration identity, CSV provenance, and UI clear,
reopen and superseded async reads with DOM/decoder doubles. Generated HTML
labels/IDs/links, module syntax/imports and local assets were checked. Native
browser decoding and visual/device QA have **not** been run for this addition.

Technical references: [PNG header](https://www.w3.org/TR/png-3/#11IHDR),
[WebP container](https://developers.google.com/speed/webp/docs/riff_container),
[WebP lossless dimensions](https://developers.google.com/speed/webp/docs/webp_lossless_bitstream_specification),
[ImageBitmap orientation](https://developer.mozilla.org/en-US/docs/Web/API/Window/createImageBitmap),
[Web Mercator transform](https://proj.org/en/stable/operations/projections/webmerc.html).


## Downloadable offline tools — October 5, 2026

**Download offline tools** in the preparation-desk header now offers a standalone
HTML copy (approximately 122 KB) containing the source planner, GPX inspector and
local map-image viewer. Save the file and reopen it in a current desktop browser.
Keep original maps/GPX files and explicitly exported plans, bounds and CSVs
separately; downloading the tools does not embed open files or current selections.

The one-file copy has inline styles, scripts, favicon and region metadata. It
requires no external modules, stylesheets, fonts or images, no local web server
and no service worker. It does not access browser storage, call providers, check
for updates or upload user data. The website itself is still not an installed
offline app. Local image limits, georeferencing limitations and secure-SHA-256
requirements remain unchanged. Phone/tablet file previews may not execute local
HTML; browser/device testing remains pending.

The source planner's provider actions lead to an online-portal panel. Its button
asks for confirmation before opening the fixed FieldForge website URL in a new
tab using noopener/noreferrer, without local files or coordinates. A fallback
link is revealed after confirmation for browsers blocking the new tab. The
original local tab and unsaved work remain open.

This download contains tools only: no map datasets, knowledge packs, accounts,
chat service or complete desktop application. Driving-route calculation, live
sign-in and chat hosting remain unfinished. Saved plans and image calibration
files remain separate from the desktop's verified map-download manifest.

Implementation:
- `tools/build_offline_desk.py` is invoked by the normal hosted exporter.
- It bundles the fixed shared named-export module graph into classic script,
  rejecting unsupported/unresolved imports instead of leaving local module loads.
- A Content Security Policy pins the emitted inline script/style hashes and
  denies background connections, external resources and form submissions.
- `offline-download.json` records the exact download byte size, SHA-256,
  content-derived edition ID and original portal snapshot. This is build metadata,
  not a digital signature.

Validation: **31 Node tests and 4 Python tests passed**. The new checks build
temporary copies directly from source; execute the emitted script with DOM
doubles and blocked network/storage APIs; verify source-plan save/reopen, tool
tabs, confirmation/fallback, local links, content hashes, CSP and import rejection.
Generated hosted-page labels/IDs/links and script syntax also passed. Native
local-file browser rendering and decoding were not tested.

Run from the repository root:
```sh
node --test tools/portal_preview/*.test.mjs
python tools/test_offline_desk.py
```

References: [local module restrictions](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules),
[script hashes](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/script-src),
[meta CSP](https://developer.mozilla.org/en-US/docs/Web/Security/Practical_implementation_guides/CSP).


## Saved places and desktop exchange — October 5, 2026

The website and downloadable offline edition now include **04 Saved places**.
The collection holds up to 1,000 named WGS 84 coordinates and source notes. Add or
edit manually, collect a selected GPX point, collect all explicit GPX waypoints,
or collect a map-image pixel after applying geographic bounds. Copying a point
does not verify its geographic accuracy. Clearing the GPX/image does not remove
points explicitly copied into this separate collection.

The tool supports name/source search, 50-row pages, removal, one-step undo and
confirmed clear. It runs in tab memory without uploads, account synchronization
or browser storage. **Save collection JSON** keeps all original numbers and
labels for reopening. There is no automatic save.

JSON/CSV imports are bounded to 4 MiB and 1,000 places with strict UTF-8 decoding.
CSV supports only name, latitude, longitude and optional source. Imports append
validated records and skip exact name/coordinate/source duplicates; any invalid
record rejects the whole file. Cancelling a read or changing the collection
discards late import results. Strings are rendered as text, not executable markup.

CSV and GPX export every search match across pages; collection JSON exports all
records. CSV targets the GPS place catalog. Waypoint-only GPX 1.1 targets the
desktop Places importer, with at most 200 matching records, source notes in
descriptions, escaped text and +180 normalized to -180 after seven-decimal
rounding. GPX checks duplicate names; the desktop can still report existing-name
or Unicode comparison conflicts. CSV protects formula-like names and sources.
Labels already at maximum length must be shortened by one character for this
protection or exported as JSON/GPX. Exports are plain, unencrypted files.

GPX tracks, elevation and other metadata are not retained by the collection;
keep original input files. Source labels are user-supplied and not independently
verified. Search is local to the collection, not address lookup or route planning.

Verification: **42 Node tests + 4 Python tests passed**. Added checks cover limits,
precise JSON/coordinate editing, CSV quoting and malformed rows, atomic capacity
rejection, duplicates, source retention, XML escaping/date-line boundaries, search,
edit/undo, filtered versus complete export, import cancellation and offline
execution with network/storage APIs forbidden. Generated HTML IDs/labels/links,
module imports, script syntax and the standalone CSP also passed.

Generated CSV and GPX fixtures were accepted by the actual repository readers
`fieldforge_gps.places.parse_catalog` and `fieldforge.navigation.gpx.parse_gpx`
from source `1a596c257beb0d6616369462bfff2d219a80f858`. Four records exercised
zero, date-line normalization, Unicode and escaped source descriptions. Native
browser rendering, desktop UI execution and mobile behavior were not tested.
The downloadable HTML is now approximately 150 KB.

Reference: [GPX 1.1 schema](https://www.topografix.com/GPX/1/1/). Field names and
record limits were checked against the project's current importer sources.

## Printable place sheets and point-to-point estimates (October 5, 2026)

**Saved places → Prepare your field sheet** now creates a separate, printable
HTML file from all current search matches across list pages. The limit is 100
places per sheet; larger selections must be narrowed and are never silently
truncated. Users choose a title and whether to include source notes, inspect a
preview, then download and open the file to use their browser's Print / Save as
PDF command. The generated file uses system fonts, print styles and no scripts
or external resources. It is a fixed snapshot, not an editable collection or map.

An optional pair of selected places produces approximate great-circle distance
and initial **true** bearing, in metric or imperial distance units. The model
matches the desktop Places spherical calculation (radius 6,371,008.8 metres).
Coincident/extremely close, near-antipodal and polar-start cases suppress a
meaningless or unstable bearing. No magnetic declination, roads, travel time,
terrain, obstacles or access assessment is supplied. Both endpoints must appear
among the places on the sheet.

Relevant collection, search-result, endpoint or option changes clear the
prepared preview and disable its download until prepared again. Pagination
alone preserves it. Capture validates and copies the records; user labels are
rendered as text / escaped HTML. Omitting source notes removes their contents
from both the preview and downloaded HTML, including comparison output.
Exports contain precise coordinates in plain text, rounded to seven decimal
places. Save collection JSON separately for full numeric precision and editing.
Already downloaded files cannot be updated by subsequent collection edits.

The website and standalone offline download include the same feature. The new
offline edition is **67e72fc29180**, 171,038 bytes, and retains the existing
no-network/no-storage behavior. It contains tools, not users' data or map datasets.

Validation: **50 Node tests and 4 Python tests pass**. New checks cover cardinal
directions, date-line crossings, degenerate bearings, unit formatting, frozen
captures, endpoint membership, output escaping, optional-note omission, filtered
exports, the 100-place limit, pagination and stale-preview invalidation. The
actual bundled offline script is exercised with a DOM double and forbidden
network/storage APIs. Eight coordinate pairs also matched distance and bearing
from the actual desktop `fieldforge.navigation.places.estimate_leg` source at
`1a596c257beb0d6616369462bfff2d219a80f858`. Built HTML IDs, label targets and
local script/style assets were checked. Native browser rendering, physical
printing/PDF pagination, desktop UI and phone behavior have not been tested.

This addition does not activate hosted accounts, live messaging, address search,
routing, billing or map-data hosting. Existing source links and other portal
sections retain their stated status.

## Offline GeoJSON vector layers (October 5, 2026)

The preparation desk now includes **Vector layers**, available on the website
and in its standalone offline HTML download. Users open a local WGS 84 GeoJSON
file, view points / lines / polygons, select a drawn feature or choose it in a
searchable feature list, inspect its coordinate vertices and properties, and
copy a selected vertex into Saved places. That collection can then produce the
existing CSV, GPX, JSON and printable field sheets. The selected feature can
also be exported as GeoJSON with its geometry, properties and optional ID.
Other top-level feature metadata is omitted; retain the original source.

The renderer uses native SVG paths and circles with bounded 1–8× zoom, pan and
fit controls. Polygon rings use separate even-odd subpaths to retain holes.
The view is north-up, linear longitude / latitude (plate carrée), not a basemap,
a measured ground-distance view or a navigation route. A selected vertex is an
actual file position, not a centroid or inferred destination. Source filename
and an unverified-coordinate label accompany points collected into Saved places.
Properties are rendered as text, never active HTML or links; nested properties
are summarized onscreen but retained in feature exports.

Supported geometry types: Point, MultiPoint, LineString, MultiLineString,
Polygon, MultiPolygon and GeometryCollection. Limits: 4 MiB UTF-8, 1,000
features, 10,000 positions, 2,000 geometry parts and eight nested collection
levels. Coordinates must be finite longitude / latitude with optional finite
altitude. Altitude is retained in feature export but not used in this 2D view
or Saved places. Null feature geometries are counted and cannot produce a
selected coordinate. Empty geometry arrays are rejected. Polygon closure is
checked; topology, winding, source accuracy and access rights are not verified.
Legacy CRS declarations are rejected. Edges spanning over 180° longitude must
be split before import; split date-line parts appear on opposite sides of the
unwrapped longitude view. Supplied bounding-box metadata is not used for fitting.

Opening a new file clears previous geometry and selected coordinates. Invalid
files reject as a whole. Clear/cancel and later file choices invalidate earlier
asynchronous reads. No file content is uploaded or automatically persisted.
Clearing the viewer does not delete points already collected or exported files.

Validation: **58 Node tests and 4 Python tests pass**. New checks exercise all
supported geometry types, hole subpaths, finite projection, zero/polar/date-line
coordinates, invalid geometry and resource limits, provenance and export
retention. The actual offline bundle runs against a DOM double with network and
storage forbidden; tests cover feature selection, vertex collection, local
export, zoom, failed imports, UTF-8 rejection, cancellation and superseded reads.
Built HTML IDs, labels, ARIA targets, local assets and module imports were
checked. These are automated DOM/structure checks, not native browser rendering,
phone or physical printing QA.

The new offline edition is **fe0749353e8b**, 197,901 bytes. No third-party runtime
or online asset dependency was added. GeoJSON support does **not** provide
browser MBTiles/vector-tile decoding, shapefile/KML/GeoTIFF support, map datasets,
routing, hosted chat or accounts.

Format reference: [IETF RFC 7946](https://www.rfc-editor.org/rfc/rfc7946.html).

## Local raster MBTiles viewer (October 5, 2026)

The website and standalone offline desk now include **MBTiles maps**. Users
choose a local pack, browse stored zoom levels, pan or enter a coordinate,
inspect attribution as plain text, select a displayed pixel and add that
coordinate to Saved places. The first view uses an actually stored tile rather
than assuming worldwide coverage or trusting declared centre metadata.
Coordinates are calculated from Web Mercator pixel centres; missing or
undecodable tiles cannot supply a selected point.

This release supports a bounded subset consistent with the desktop reader:
closed rollback-mode SQLite files up to 64 MiB; ordinary metadata and tiles
tables with the expected columns; a unique non-partial BINARY index on
zoom_level, tile_column, tile_row; MBTiles/TMS rows; integer zoom levels 0–22;
and square 256/512-pixel PNG, JPEG or still WebP raster tiles. Metadata is limited
to 128 rows, with 128-byte names and 16-KiB values. Each compressed tile is at
most 2 MiB and each frame at most 16 MiB. Supported zoom availability is not
a coverage, integrity, freshness or route-safety audit.

The initial raster release rejected vector MBTiles, normalized/view-based
layouts, WAL-mode exports and larger files. The vector update below adds
browser support for compatible PBF packs; the other exclusions remain.
Compatible larger packs can use the desktop map viewer. Normalized or
view-based databases and WAL-mode files need a flat, indexed, rollback-mode
export first. The browser viewer does not acquire datasets, calculate routes,
follow GPS or verify conditions.

The original File is never written. SQLite opens an in-memory copy with
query_only and trusted_schema restrictions. SQL uses fixed queries, bound tile
coordinates and quoted index identifiers. All database work runs in a disposable
worker; a 15-second request deadline or Close / cancel terminates it. New files
and frames clear selected coordinates and release old bitmaps. FileReader operations are abortable, have their own 15-second deadline, and
are generation-checked. Replacement opens do not wait on canceled reads or
native decodes; stale results are discarded and eventual bitmaps released.
Native image decoding is preceded by format, dimension and byte-size checks.
A labelled blank tile reports missing, unsupported or out-of-projection data.

SQL.js **1.14.2**, MIT licensed, is vendored from the verified npm release with
its licence and provenance. The package tarball's SHA-512 integrity and
vendored file SHA-256 are recorded and checked; the build rejects a changed
reader checksum. No CDN or runtime download is needed. The reader is embedded
as inert base64 and instantiated only on opening a pack. The offline CSP allows
local blob workers while retaining connect-src 'none', hashed scripts/styles
and no unsafe-eval or unsafe-inline. Dependency licence text is included in
both website and offline file.

Validation: **68 Node tests and 4 Python tests pass**. Independent Python SQLite
fixtures verify flat/indexed reads, actual stored zooms, TMS orientation, byte
preservation, read-only SQL, oversized blobs, malformed metadata, unsupported
schemas and Mercator/date-line math. The built worker runs with network, dynamic
evaluation and WebAssembly compilation disabled. DOM/bitmap doubles test
selection, stale decoding, replacement, cancellation and resource disposal;
client doubles test byte transfer, ignored late replies and worker termination.
The complete downloaded HTML also opens a synthetic pack through its embedded
reader and exports a selected coordinate, using a worker bridge with actual
structured-clone transfers, real SQLite and DOM/bitmap doubles.
Built HTML label/ARIA targets, local module assets and exact embedded worker
bytes were checked. Native browser worker startup, Canvas/image decoding,
phone behavior and physical printing remain untested in this environment.
Test fixtures are synthetic; no new real map datasets are claimed or shipped.

The updated offline edition is **0bccb4e66240**, 2,044,099 bytes. The size increase
is the self-contained SQLite reader. The offline size-budget test now allows
3 MiB to accommodate it; network and CSP checks remain in place.

References: [MBTiles 1.3 specification](https://github.com/mapbox/mbtiles-spec/blob/master/1.3/spec.md),
[SQL.js](https://github.com/sql-js/sql.js).


## Browser vector MBTiles preview (October 5, 2026)

The **MBTiles maps** tab now opens local PBF vector packs as well as raster
packs. This is also included in the standalone offline download. Raw and
gzip-compressed Mapbox Vector Tiles (MVT versions 1 and 2) are decoded inside
the existing disposable SQLite worker. No map data, style, font or sprite is
downloaded or uploaded. The original file is never written.

The fixed Canvas preview draws polygon areas with holes, lines and points.
Common source layer/class names choose water, land, building, road, boundary
and rail colours; other features use a neutral style. Geometry is clipped to
each tile. A **Show point names** control toggles available source point names,
with overlap suppression. Publisher styling, symbol sprites, detailed road
labels and full cartographic accuracy are not reproduced. An empty decoded
tile has a neutral background; it does not establish anything about terrain.

Navigation, stored zoom selection and coordinate collection work with either
format. Saved-place source notes identify vector MBTiles and the basic preview
style. Coordinates are Web Mercator pixel centres, not feature identities or
verified access/navigation guidance. Damaged or unsupported vector tiles show
an issue while usable neighbours remain available; missing/unreadable tiles
cannot supply selected coordinates.

The existing 64-MiB closed, flat/indexed MBTiles file restriction, TMS rows,
zoom 0–22, 2-MiB tile input and 16-MiB compressed frame limits still apply.
Vector limits additionally include 8 MiB expanded per tile, 64 layers, 5,000
features, 50,000 positions and 250,000 geometry/tag words per tile. Each frame
accepts at most 10,000 features and 100,000 positions; tiles crossing that
budget are omitted with an explicit issue. Extents are 1–65,536 and coordinate
buffers are limited to one tile width outside the tile. Invalid UTF-8, broken
protobuf, missing tag references, malformed geometry and unsupported formats
are rejected. Gzip expansion is bounded while streaming and requires browser
DecompressionStream support. The worker remains subject to a 15-second
deadline and Close / cancel termination.

Point names are cleaned of control and bidirectional override characters,
limited to 48 code points and drawn as text, never as markup. At most 32 names
per tile and 96 per frame are drawn. No dynamic CSS, code or URLs are taken
from feature properties.

Validation: **75 Node tests and 4 Python tests pass**. Independent Python
SQLite/protobuf fixtures cover raster tiles, raw and gzip MVT with known
coordinates, a polygon hole, a road and a named point. Checks cover malformed
data, gzip checksum failure and expansion limits, per-tile/frame budgets,
Canvas clipping/fill commands, selection/export and resource cleanup. The
actual downloadable HTML opens a mixed valid/damaged vector pack through its
embedded worker, draws the usable geometry and exports a selected coordinate
with network and browser storage access forbidden. Canvas and DOM are test
doubles: native browser rendering/worker startup and phone QA remain
outstanding. No real map datasets were added or claimed.

Offline edition: **68822322cc5c**, **2,062,946 bytes**. Built HTML label/ARIA
targets, local assets and embedded worker bytes were checked. Hosted chat,
accounts, map hosting, geocoding, routing and world-data acquisition remain
separate unfinished work.

References: [Mapbox Vector Tile specification](https://github.com/mapbox/vector-tile-spec),
[version 2.1 protobuf schema](https://github.com/mapbox/vector-tile-spec/blob/master/2.1/vector_tile.proto),
[DecompressionStream](https://developer.mozilla.org/en-US/docs/Web/API/DecompressionStream).
