# Saved trips over local maps

> This guide describes tested local integration `fe70c8b`. Publication and
> graphical/Windows execution remain pending. See
> [map integration status](../MAP_INTEGRATION_STATUS.md).

The integrated workspace overlays a read-only saved GPX journey on the included
overview or a supported local raster/vector MBTiles pack. A recorded line is
not evidence of a traversable road, legal access, current safety or accuracy.

## Workflow and independent permissions

Open **Navigation → Maps, GPS & places…** in the main desktop, then
**Show GPX controls** for saved-history review. Source users can run
`python -m fieldforge_gps --workspace` or the existing standalone
`python -B -m fieldforge_gps.local_map_ui` launcher.

GPX confirmations govern private-history reading. A separate checkbox governs
trusted external map files. **Included U.S. atlas…** explicitly opens the known
application resource without the external-file checkbox. Permissions are not
saved. A modal file chooser rechecks permission before reading; cancelling it
changes nothing. A failed map-open does not erase the historical GPX document.

Map opening, pan and zoom do not start receiver capture. Clearing GPX leaves an
independently loaded map open, and closing the map preserves GPX. Revoking an
external-file permission clears its respective workspace. **World overview**
closes the map pack and returns to the coarse outline. Source/rights details
are inert text; displaying them does not fetch their URLs.

## Included atlas and town actions

The integration includes **615 overview tiles** in `USA-OVERVIEW.mbtiles` and
**777 selected town reference points** in `USA-OVERVIEW-PLACES.csv`.
**Included U.S. atlas…** offers lower-48, Alaska, Hawaii and named territory views.

In the combined GPS workspace, choose **Find places / coordinates… → Included
U.S. towns**, search, select a result, then **Show selected place on map**.
The reference point centers the current map or coarse outline; it does not
automatically replace the current map with the atlas. Receiver following pauses
until explicitly re-enabled. No saved waypoint or route is created.

The main Maps tab instead has **Find included U.S. towns… → Show selected town on
included atlas**, which opens that atlas with a temporary marker.
**Clear town marker** removes the marker.

The overview uses generalized Natural Earth 1:50 million geography, including
state outlines, selected city labels, rivers and lakes. The catalogue uses
a separate 1:10 million populated-places selection. It is not all towns,
street addresses, street detail, terrain, current hazards or a routing graph.
Small islands and features may be omitted. See [bundled atlas](../BUNDLED_ATLAS.md).

`FICTIONAL-MAP.mbtiles`, `FICTIONAL-REVIEW.gpx` and synthetic receiver examples
remain separate, clearly fictional practice data.

## Supported MBTiles subset

Both viewers accept indexed flat `metadata`/`tiles` and normalized
`metadata`/`map`/`images` storage. Normalized files use the readers' own fixed
join over ordinary tables; file-supplied views are never executed. Coordinate
and image-ID indexes must be unique, non-partial and BINARY-collated.
Other view-only layouts, virtual tables and generated columns are unsupported.
No source repair or index creation is performed.

Contents may be square 256/512-pixel PNG/JPEG/WebP images or gzip-compressed
MVT/PBF vector tiles. Vector previews use a basic style with bounded embedded
point/line/area names; publisher styles, fonts, sprites and advanced label rules
are not applied. Animated map tiles are unsupported.

Observed integer zooms must lie between 0 and 22. Required metadata includes
`name` and the supported `format`; an explicit `scheme` must be TMS. Metadata
is bounded to 128 entries, 128 bytes per key and 16 KiB per value. Declared
zoom/bounds metadata is not proof of coverage.

Use closed rollback-mode files with no nonempty WAL/journal/SHM sidecars.
URL/UNC inputs are refused; mapped network filesystems cannot always be detected.
The optional portal publisher remains **flat-only**, even though normalized
files can be opened locally. See [schema details](../OFFLINE_MAPS.md#open-a-supported-external-map).

## Projection, overlays and missing data

Map tiles use Web Mercator/TMS placement. Coordinates outside approximately
±85.05112878° are not clamped onto the map. Polar points remain inspectable
and break the displayed history runs; use the coarse world overview to view them.

File-defined GPX segments remain separate. The preview caps history at 8,000
samples and reports full-file counts and exclusions. Preview simplification
does not create connections across file segments or known polar exclusions.
Unknown gaps absent from the source cannot be reconstructed.

Date-line crossings use the shorter longitude arc, with clipping at viewport
edges. Tiles repeat horizontally; polar rows do not. Missing tiles, bad data,
readable tiles and cells outside projection have distinct states. Visible-cell
counts may include repeated world copies. Old imagery is cleared while a new
frame loads and is not reused under changed coordinates.

**Pack start** uses a valid declared center/observed zoom, or an explained
observed-tile fallback. Neither is the device's current location.
Attribution, bounds, dates and rights remain source-supplied information.
No full-pack integrity scan, license authentication or safety assessment is implied.

## File/thread safeguards and limits

SQLite is read-only and query-only, with trusted schema disabled and one
transaction per viewport. File identity/size/modification metadata is checked
around reads. Changed files fail; close and reopen to accept another version.
These are ordinary change checks, not a tamper-proof snapshot or protection
against malicious path races or restored timestamps.

One worker and a replaceable pending request use cancellation and generation
tokens. Obsolete results cannot repaint a newer view or restore a closed map.
Workers do not own Tk objects. Widget changes and Tk image drawing stay on the
UI thread. Disk I/O and image decoding are not forcibly terminated.

Limits are 16 GiB per pack, 2 MiB source bytes per tile, 32 MiB of unique
source/display-PNG buffers per frame (whichever is larger for each tile),
96 visible cells and a 2560 × 1600 canvas. SQLite uses a four-second progress
deadline, a 20-million-instruction cap and a 250 ms lock timeout. These are
guards, not throughput guarantees for large or damaged storage.
Only trusted files should be opened with maintained dependencies.

## Regional indexes and saved online routes

The main Maps tab's separate **Prepared regional map…** viewer opens `.ffmap`
indexes, imports `map.ffmap` from supported regional ZIPs, and offers
**Prepare PBF…** for local OSM snapshots. These are display/search indexes, not
routing graphs. The current portal does not distribute them or extract their ZIPs.
The documented four-state Wave 5 collection is not a bundled full U.S. street database.

Configured online tools can request driving-route alternatives while connected.
Saved directions and planned geometry remain readable/exportable as GPX offline.
Neither GPX overlays, MBTiles rendering nor `.ffmap` preparation calculates a new
offline route. See [Offline Maps](../OFFLINE_MAPS.md) and
[Online map portal](../ONLINE_MAP_PORTAL.md).

## Verification

Fresh headless results, installed-package byte comparisons and socket-forbidden
checks are recorded in [map integration status](../MAP_INTEGRATION_STATUS.md).
GUI, Windows, receiver hardware and native mobile execution remain pending for
this snapshot. Headless tests do not establish those operational results.
