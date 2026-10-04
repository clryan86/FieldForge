# Online preparation, offline use

FieldForge starts offline. The optional portal supplies address matches, published
map files and planned driving routes. Saved coordinates, MBTiles, map images and
GPX files open through the existing offline readers without a portal connection.

This repository includes the desktop client, browser portal and WSGI service.
It does **not** include a deployed public portal, worldwide map packs, or a
geocoding/routing subscription. An operator must host the service, configure
providers and publish maps they have permission to redistribute. The example
configuration is deliberately empty; it never selects a public provider for you.

## Desktop workflow

1. Open **Navigation → Online map portal…**. Enter the operator's HTTPS URL,
   acknowledge sending entered queries/route coordinates, and choose **Connect**.
   `FIELDFORGE_MAP_PORTAL` can prefill the URL; it does not connect automatically.
2. **Address search:** enter an address with city/country and press Search. There
   is no autocomplete. Choose a possible match explicitly. **Use coordinates**
   fills the GPS workspace's manual coordinate fields for review; **Show
   coordinate** remains a separate action. **Copy lat, lon** and **Save place
   CSV…** work on the selected result, including after disconnecting.
3. **Places → Add/Edit → Find address online…** fills the place editor's name,
   latitude, longitude and source note. Close the portal, review the fields, and
   choose **Save place**. Search never writes a household record automatically.
4. **Download maps:** load the catalogue, inspect coverage, date and attribution,
   select a file, and choose a new destination. The desktop checks the declared
   size, SHA-256 and offline decoder before publishing the file and its
   `.source.json` companion. **Open downloaded map** also works offline.
5. **Plan & save route:** use selected address matches as endpoints or enter WGS84
   latitude/longitude. Request a driving route, then save GPX. Open it using the
   workspace's GPX controls. The GPX contains a **PLANNED** track, not a recorded
   trip, and supplies no invented point timestamps. Download its regional map
   separately. There is no offline route calculation, rerouting or turn guidance.
6. **Go offline / cancel** disables online controls, cancels unfinished work and
   rejects late results. A failed desktop request also returns the window to
   offline mode. Reconnect explicitly; there are no background retries.

Disconnecting cannot retract a request already received by the server. An active
socket read may take up to its eight-second timeout to return. Selected results
stay in memory until the window closes; saved files remain yours. Place CSVs are
opened through **Find places / coordinates… → Open place CSV / GeoJSON…**, with the normal
local-file/WGS84 confirmation. Maps, CSVs and GPX exports are external files and
are not included in household database backups.

## Browser workflow

Open the portal URL, acknowledge sending entered queries and choose **Connect**.
Search, select, copy or save a place CSV; fill route endpoints and save planned
GPX; download map packs and source notes. Loss of connectivity disables search
and map links. Restoring connectivity does not reconnect automatically.

The browser page itself requires the portal to load; it is not a service worker
or a replacement for the offline desktop. There are no CDN scripts, analytics,
automatic searches, cookies or local-storage records. Downloaded files can be
transferred to an offline computer. Browser map downloads use the browser's
download manager: **Go offline** stops portal API work, but cancel an already
started file download in that manager. Save its source note and compare the
SHA-256 before opening; automatic checksum/decoder verification is provided by
the desktop downloader. Source notes do not establish accuracy or safety.

## Run a local portal

From a source checkout:

```sh
python -m pip install -e ".[maps]"
python -m fieldforge.map_portal --config examples/map-portal.json --port 8765
```

Open `http://127.0.0.1:8765` in a browser, or enter that URL in the desktop.
The installed equivalent is `fieldforge-map-portal --config /path/portal.json`.
This development server binds only to loopback. With the empty configuration,
the catalogue is empty and address/route controls explain that their providers
are not configured. No household database or account is needed for the portal.

## Configure providers

Use an owned or contracted **Nominatim-compatible search endpoint** and
**OSRM-compatible driving endpoint**, reachable over HTTPS. Each configuration
object has `url`, `name`, and `attribution`, for example:

```json
{
  "url": "https://your-owned-geocoder.example",
  "name": "Your search provider",
  "attribution": "The actual data attribution required by your provider"
}
```

Set this object as `geocoder`; set an equivalent routing object as `router`.
Use base URLs, without `/search` or `/route/v1/driving`, query strings, embedded
credentials or redirectors. HTTP is accepted only for localhost development.
Providers needing API-key headers require an operator-controlled adapter; keys
must never be put into map manifests, client URLs or browser JavaScript.

The service sends Nominatim `q`, `format=jsonv2`, `limit=5`, and uses OSRM full
GeoJSON route geometry. The desktop API takes **latitude, longitude**; the
adapter converts to OSRM's **longitude, latitude** order. Each provider instance
has a nonblocking request gate (one new request per 1.1 seconds), plus a ten-minute
in-memory cache limited to 128 entries and 16 MiB of serialized responses. This
is per process, not a deployment-wide quota or a persistent address database.
Provider responses remain in memory during their cache lifetime. The operator
must enforce its contract's total rate, retention and access rules externally.

No community public/demo service is a default; known Nominatim/OSRM community
hosts are rejected. OSM's standard tile endpoint forbids offline bulk downloads.
Use licensed prepared packs or your own map infrastructure. Relevant primary
references: [Nominatim search API](https://nominatim.org/release-docs/latest/api/Search/),
[OSRM API](https://project-osrm.org/docs/v5.24.0/api/),
[Nominatim policy](https://operations.osmfoundation.org/policies/nominatim/), and
[OSM tile policy](https://operations.osmfoundation.org/policies/tiles/).

## Publish regional maps

`asset_folder` is relative to the configuration file. Put regular map files
directly in it and add entries to `maps`. A manifest entry has these fields:

| Field | Meaning |
| --- | --- |
| `id` | Distinct lowercase letters, digits and dashes; maximum 80 characters |
| `title`, `coverage` | Human-readable title and actual geographic coverage |
| `filename`, `kind` | Portable basename; kind `mbtiles` or `image` |
| `size`, `sha256` | Exact byte count and lowercase SHA-256 of the published file |
| `updated` | Actual source revision/vintage, or explicitly unknown |
| `source`, `attribution`, `license` | Actual origin, required credit and redistribution terms |

For example, obtain a file's size/hash without loading it all into memory:

```python
import hashlib
from pathlib import Path

path = Path("maps/your-region.mbtiles")
digest = hashlib.sha256()
with path.open("rb") as stream:
    for block in iter(lambda: stream.read(1024**2), b""):
        digest.update(block)
print(path.stat().st_size, digest.hexdigest())
```

Catalogue limit: 500 files; MBTiles limit: 16 GiB; images: 64 MiB. File names must
be ASCII letters/digits/dot/underscore/dash with no path components or Windows
device names. Start-up verifies each file's size/hash. Restart with an updated
manifest when replacing files; never modify a published file in place.

Supported MBTiles are flat, indexed **raster** packs using PNG/JPEG/WebP, Web
Mercator/TMS, 256- or 512-pixel square tiles. Vector/PBF and normalized/view-based
MBTiles are unsupported. Supported map-image families include PNG, JPEG, WebP,
TIFF, BMP, GIF, ICO, PPM, TGA, JPEG 2000 and AVIF, subject to installed codecs.
Images remain uncalibrated references, without GPS overlays or GeoTIFF/world-file
interpretation. See [GPS workspace](GPS_WORKSPACE.md) and [map limits](OFFLINE_MAPS.md).

## Production service

Deploy `fieldforge.map_portal.create_app("/absolute/path/portal.json")` with a
production WSGI server behind HTTPS. For example, an operator-owned `portal_wsgi.py`
can expose `application = create_app(...)`. Serve at the site's root: browser
asset/API paths are absolute. Do not expose the `wsgiref` development server.

Terminate TLS with a trusted proxy that supplies the correct WSGI URL scheme and
Host; same-origin POST checks depend on those values. Configure request-size and
time limits, deployment-wide quotas, bandwidth limits and provider egress. The
portal API has no built-in authentication or billing. Choose public access only
when intended; private deployments need access controls compatible with the
desktop client (which sends no browser session cookies).

The app does not log queries, but your proxy, WSGI host and upstream providers
may. Keep address/coordinate bodies and upstream query URLs out of access logs.
Serve a separate directory of approved map packs; never point it at household
files or allow untrusted writers to change active map files/configuration.

## Verification

`tests/test_online_portal.py` exercises real localhost HTTP, provider adaptation,
offline gating, result validation, checksum/image validation and partial-file
cleanup. `tests/test_online_maps_ui.py` exercises real Tk actions, reviewed
place saves and cancellation. `tests/test_online_portal_browser.py` runs in the
Chromium/WebKit CI jobs and reopens browser exports with the offline readers.
Fixtures are fictional; these checks do not establish real provider coverage,
address accuracy, route suitability or a working public deployment.
