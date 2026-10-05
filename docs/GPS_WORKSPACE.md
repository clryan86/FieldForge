# GPS, local maps and offline places

Open **Navigation → Maps, GPS & places…** in the main FieldForge desktop.
This opens the combined map and receiver workspace in the same application.
Opening it does not connect a device, read a place catalogue, show a live
position, or start trip recording automatically.

Use **Find places / coordinates…** to read your chosen local CSV or Point
GeoJSON, or enter a latitude and longitude. Showing a reference point pauses
GPS following and leaves live display available. Re-enable **Follow receiver**
explicitly to return to a fresh receiver fix. Rejected inputs preserve the
previous view and following setting.

**Show GPX controls** opens the historical-trip controls. **Receiver controls…**
opens the serial input and explicit trip-recording controls. The receiver,
historical GPX, reference markers and local map permissions remain separate.
Nothing is copied into the household database. Export wanted trips as GPX;
database backups do not include this workspace's in-memory trip or external maps.

Closing the main desktop checks for unsaved GPS history and allows cancellation.
Closing just the map leaves the receiver and trip available in its controls.
Reopening the map starts with cleared place data and live-display permission.

For source installations, `python -m fieldforge_gps --workspace` and
`Start FieldForge Workspace.cmd` remain available. Serial hardware requires
the optional dependency installed with `pip install ".[gps]"`. JPEG/WebP tiles
and map-image references require `pip install ".[maps]"`. The Windows
build includes the serial adapter and image codecs; no device is opened by installation checks.

The package includes six fictional place records, a fictional test-grid map,
synthetic receiver/GPX examples, and an inherited coarse land outline. These
are not local coverage or verified locations. Real data acquisition on other
development branches is separate from this integration.

See [place formats](gps/PLACES.md), [live fixes](gps/LIVE_MAP.md),
[receiver setup](gps/GPS_RECEIVER.md), and [trip capture](gps/GPS_TRIPS.md).
Physical GPS accuracy, road routing, safe access, and native mobile operation
are not established by the automated software tests.

## MBTiles and image files

Both the main Maps tab and this workspace display flat, indexed MBTiles with
PNG, JPEG (`format=jpg` or `jpeg`) or WebP raster tiles, plus gzip-compressed
Mapbox Vector Tile PBF. Raster tiles must be square, 256 or 512 pixels, in Web
Mercator/TMS layout. Vector tiles use a basic preview renderer with limited
labels from embedded point-feature names; publisher styles, fonts, sprites and
label-placement rules are not applied. Existing read-only
checks, size limits, missing-tile labels and source/rights inspection remain.
Animated tiles and normalized/view-based databases are unsupported. See
[MBTiles details](OFFLINE_MAPS.md).

Choose **Navigation → Open map image…**, or **Open map image…** inside the
workspace. Confirm local-file permission, then select an image. Supported
formats are PNG, JPEG, WebP, TIFF, BMP, GIF, ICO, PPM-family images, TGA,
JPEG 2000 and AVIF, subject to the installed Pillow codecs. Format is detected
from the file bytes. The viewer offers fit, actual pixels, zoom, mouse dragging
and arrow-key panning. Source files remain unchanged.

Images are **uncalibrated references**: there is no GPS/GPX overlay, geographic
coordinate readout, ground distance or bearing. GeoTIFF tags, world files and
EXIF GPS/orientation are not interpreted. Multi-page/animated files show only
the first page/frame in stored pixel orientation. PDF, SVG, HEIC and proprietary
GIS formats are not decoded by this image viewer.

Image limits are 64 MiB, 32 million decoded pixels and a 32,768-pixel side;
a rendered viewport is limited to four million pixels. Loading and resampling
run off the UI thread. Clear, permission revocation, replacing a file and close
remove old imagery; obsolete work cannot repaint it. Regular disk I/O and image
codec work cannot be forcibly interrupted, so closing requests worker shutdown.
Images are not stored in the household database or included in its backups.

## Optional online preparation

**Navigation → Online map portal…** supplies explicit address lookup, map downloads
and planned driving-route GPX when connected to an operator-configured portal.
The workspace itself continues to read local files offline. See
[Online map portal](ONLINE_MAP_PORTAL.md) for setup, saving coordinates and maps,
provider requirements and the limits of planned route geometry.
