# GPS, local maps and offline places

> This guide describes tested local integration `fe70c8b`. Publication is pending;
> see [map integration status](MAP_INTEGRATION_STATUS.md).

Open **Navigation → Maps, GPS & places…** in the main desktop.
Opening the workspace does not connect a receiver, read a place catalogue,
display a live position, or start trip recording automatically.

## Included atlas and towns

The application resources include **615 overview tiles** in `USA-OVERVIEW.mbtiles`
and **777 selected town reference points** in `USA-OVERVIEW-PLACES.csv`.
They open offline without importing or downloading a map.

1. Choose **Included U.S. atlas…**, select a region, then **Open selected overview**.
   Choices cover the lower 48, Alaska, Hawaii, Puerto Rico / U.S. Virgin Islands,
   Guam / Northern Mariana Islands, and American Samoa.
2. Choose **Find places / coordinates…**, then **Included U.S. towns**.
3. Search by name, alias, country/area or region, select the intended result,
   then choose **Show selected place on map**.

The GPS finder centers a reference marker on the map already open, or on the
coarse outline if no pack is open. It does not replace the current map with the
atlas automatically. Showing a point pauses receiver following. Re-enable
**Follow receiver** explicitly to return to an eligible fresh fix.

The main **Maps** tab has **Find included U.S. towns…** and **Show selected town
on included atlas**. That action opens the included atlas at the selected point;
**Clear town marker** removes the temporary marker. Neither workflow creates a
saved household waypoint or a route.

The overview uses generalized Natural Earth **1:50 million** land, state,
city, river and lake layers. The separate **1:10 million** populated-places
selection adds town reference points without increasing the map's detail.
These resources are not all towns, street addresses, a full U.S. street
database, terrain elevations, current conditions, or a routing graph.
Small islands and features may be omitted. See [bundled atlas](BUNDLED_ATLAS.md)
for provenance, rights and coverage. Fictional place/test-grid/receiver/GPX
examples and the inherited coarse outline remain separate practice resources.

## External files, receiver and history

**Find places / coordinates…** also reads a selected local CSV or Point GeoJSON
or accepts manual latitude/longitude. External files require their permission
and WGS84 confirmations; the explicit included-data actions read known application
resources independently of those checkboxes. Rejected inputs preserve the
previous view and following setting.

**Show GPX controls** opens historical-trip controls. **Receiver controls…**
opens serial input and explicit trip recording. Receiver, GPX, reference-point
and external-map permissions remain separate. Nothing is copied into the
household database. Export wanted trips as GPX; database backups do not include
in-memory trip history or external maps.

Closing the desktop checks for unsaved GPS history and allows cancellation.
Closing just the map leaves the receiver and trip available in their controls.
Reopening starts with cleared place data and live-display permission.

Source users can run `python -m fieldforge_gps --workspace` or
`Start FieldForge Workspace.cmd`. Serial hardware requires `pip install ".[gps]"`;
JPEG/WebP tiles and image references require `pip install ".[maps]"`.
The Windows build configuration includes these dependencies, but Windows execution
of this snapshot is still pending. No device is opened by installation checks.

See [place formats](gps/PLACES.md), [live fixes](gps/LIVE_MAP.md),
[receiver setup](gps/GPS_RECEIVER.md), and [trip capture](gps/GPS_TRIPS.md).

## MBTiles and image files

Both map surfaces accept indexed flat `metadata`/`tiles` MBTiles and supported
normalized `metadata`/`map`/`images` storage. The normalized reader uses its
own fixed join over ordinary tables and never executes file-supplied views.
Required coordinate and image-ID indexes must already exist. Other view-based
layouts, virtual tables and generated columns are unsupported.

Supported contents are square 256/512-pixel PNG, JPEG (`format=jpg` or `jpeg`),
WebP, and gzip-compressed MVT/PBF vector tiles in Web Mercator/TMS placement.
Vector tiles receive a basic built-in preview with bounded embedded point,
line and area names. Publisher styles, fonts, sprites and advanced label rules
are not applied. Animated map tiles are unsupported.

The optional portal's MBTiles publisher remains **flat-only**. A normalized
file that opens locally is not automatically eligible for portal publication.
See [Offline Maps](OFFLINE_MAPS.md) for schema, limits and read-only safeguards.

**Navigation → Open map image…**, or **Open map image…** inside the workspace,
opens an image after local-file permission is confirmed. Supported formats are
PNG, JPEG, WebP, TIFF, BMP, GIF, ICO, PPM-family images, TGA, JPEG 2000 and AVIF,
subject to installed Pillow codecs. The format is detected from bytes.
Fit, actual pixels, zoom, dragging and arrow-key panning leave the source unchanged.

Images are **uncalibrated references**. No GPS/GPX overlay, geographic readout,
ground distance or bearing is inferred. GeoTIFF tags, world files and EXIF
GPS/orientation are not interpreted. Multi-page/animated files show the first
page/frame in stored pixel orientation. PDF, SVG, HEIC and proprietary GIS
formats are not decoded by this image viewer.

Image limits are 64 MiB, 32 million decoded pixels, a 32,768-pixel side and a
four-million-pixel rendered viewport. Workers load/resample images; clear,
permission revocation, replacement and close invalidate obsolete work.
Disk I/O and codec work are not forcibly interrupted. External images need
separate backups.

## Regional indexes and optional online preparation

The main Maps tab's **Prepared regional map…** screen opens `.ffmap` display/search
indexes, imports `map.ffmap` from supported regional ZIPs, and offers
**Prepare PBF…** for a local OSM snapshot. These indexes are not routing graphs;
the current portal does not distribute them or extract their ZIPs.

**Online Maps** and **Navigation → Online map portal…** provide explicit
address lookup, verified map downloads and provider-calculated driving alternatives
when connected to an operator-configured portal. Saved directions and planned
geometry remain readable/exportable as GPX after disconnecting.
New offline route calculation and offline rerouting are not implemented.
See [Online map portal](ONLINE_MAP_PORTAL.md) and
[regional index details](OFFLINE_MAPS.md#prepared-regional-ffmap-indexes).

Fresh headless and installed-package results are recorded in
[map integration status](MAP_INTEGRATION_STATUS.md). GUI/Windows execution,
physical receiver accuracy and native mobile operation remain unverified for
this snapshot.
