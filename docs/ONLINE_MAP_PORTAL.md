# Online map preparation and offline use

FieldForge can connect to an operated map portal while the internet is available,
then keep the selected maps, coordinates, and route directions on the device.
The desktop application starts disconnected. Its local maps, saved places, and
saved routes do not require a portal connection.

## What the user does

1. Open **Online Maps** from the section selector or Navigation menu.
2. Enter the FieldForge portal URL supplied by the operator and choose **Connect**.
   A warning asks whether to go online, names the destination and defaults to
   **No**. On approval and a successful connection, the portal home opens in your
   browser. Use **Copy portal link** if the browser cannot open automatically.
3. In **Address search**, submit an address and choose the intended result.
   Results show the full location label and WGS 84 latitude/longitude. Choosing
   **Use start** or **Use destination** fills the route fields. Filling a saved
   place opens the existing editor, where **Save place** makes the record persistent.
   A selected address can also be exported as CSV for the offline GPS place catalog.
4. In **Map downloads**, load the catalog, filter by name, region, source or
   format, and sort by size to find smaller downloads. Choose a pack by coverage,
   format, version, and size. These filters keep working on the loaded metadata
   after disconnecting; they make no requests.
   Download it while connected, then open the completed local file.
5. In **Routes**, request route alternatives between the chosen coordinates.
   Inspect the route and its directions, then save the selected route locally.
6. Disconnect. Open local maps, saved places, and saved route directions as needed.

If you use the browser portal, download a route as **route JSON**, then open
**Online Maps → Routes → Import downloaded route…** in the desktop application.
Choose that file from Downloads. FieldForge validates it, saves a local copy,
and opens its directions; this import also works offline and leaves the original
download unchanged. Browser-downloaded map files can be opened through the
existing **Maps → Open local map…** or **Navigation → Open map image…** controls.

Typing into the search field does not send an address. Only submitting the query
does so. The app does not infer an address from household records or obtain the
device's location for online lookup. A result must be selected before its
coordinates are used. Several matches may describe different locations.

The address and route services are enabled only when a portal connection has
been established and the portal advertises that service. A connection failure
or explicit disconnect disables online requests. Entered coordinates and local
files remain available. The application does not reconnect automatically.

## Online and offline capabilities

| Action | Connection needed? | Data used |
|---|---|---|
| Search a new street address | Yes | Configured portal/geocoder |
| Copy or use an already selected result | No | Result retained in the session |
| Reopen a saved place | No | Existing FieldForge waypoint database |
| Load or refresh the portal catalog | Yes | Operator's published catalog |
| Filter and sort an already loaded catalog | No | Metadata retained in the session |
| Prepare, save or import a map download list | No, once the catalog is loaded | Selected map metadata and file sizes |
| Download a new map | Yes | Operator's immutable map file |
| Reopen a completed map download | No | Local MBTiles or image file |
| Request new driving-route alternatives | Yes | Configured routing server |
| Read saved route directions | No | Local route JSON |
| Import a route downloaded through the browser | No | Selected portal route JSON file |
| Show a saved route over a local map | No | Saved route geometry and local MBTiles |
| Export a saved planned route as GPX | No | Saved geometry |
| Recalculate a route after an offline detour | Not implemented | Requires a local routing engine and graph |

An image or raster MBTiles pack supplies the map picture. It is not a routing
graph. A saved route supplies the chosen path and instructions at the time it
was requested. It does not update for a road closure, changing conditions,
traffic, or a departure from that route. Alternative requests can return only
one route if the provider has no suitable alternatives.

## Select maps for a short online session

In the browser, check **Include in download list** on the maps you want. A
selection stays selected across catalog pages, sorting, filtering and a
disconnect. **Your map download list** shows the number of maps and their total
file size. Review the selected entries, remove any you do not need, then choose
**Save download list**. The resulting JSON contains the selected metadata,
checksums and source details; it does not contain the map files or start transfers.
Save it before closing the page. Browser selections are not written to browser
storage, and address/route inputs are not included in map lists.

In the desktop's **Online Maps → Map downloads**, select a catalog row and use
**Add selected to list**. Alternatively, open **Review / import list…** and import
the JSON saved by the browser or another FieldForge session. Import works
offline. Review the count, total size, filenames and required portal. The list
never changes the configured URL or starts a connection automatically. Use
**Copy required portal** if you need to paste its URL into the connection field.

When ready, connect to that portal explicitly and press **Download list**.
FieldForge refreshes the catalog once and checks every selected record is still
current before starting map transfers. It downloads the maps sequentially,
retains their provenance, and shows progress through the combined file sizes.
Verified files appear under **Downloaded maps**; the app does not open a separate
viewer for every item. The displayed total is map-file bytes, excluding catalog
and network overhead. It is not billing or a paid allowance.

**Stop downloads**, **Cancel task**, or **Disconnect** interrupts unfinished work.
Completed maps remain available offline, and the selected list is retained.
Retrying the list rechecks its current catalog records and fully verifies
matching local maps by size, SHA-256 and provenance, reusing them without another
file download. A changed, incomplete or conflicting existing local file is
preserved and reported; it is never overwritten. If the catalog changed, discard
unneeded partial files before removing obsolete selections and building a current list.

**Keep partial downloads for retry** is enabled in the list window. On Stop,
Disconnect or a dropped connection, downloaded bytes are checkpointed locally.
Retry the same list explicitly after connecting to its portal. FieldForge checks
the saved prefix, requests the remaining bytes, then verifies the complete size,
SHA-256 and map format before making the map available offline. This also works
after restarting the app and importing the saved list. For one resumable map,
add that map to a one-item list. The single-map download button and legacy
destination picker retain their temporary-file behavior.

If a server ignores byte ranges, the current file starts from zero; its full
response is never appended to an existing prefix. Inconsistent ranges or changed
server fingerprints are rejected. Completed files are still reused separately.
Unchecking **Keep partial downloads for retry** starts new temporary transfers;
it does not delete earlier partial files.

**Discard partial files…** works offline and asks for confirmation before
removing incomplete files for the maps in the current list. Completed maps and
the saved list are preserved. Clearing/removing list items does not free partial
storage; discard unneeded partials first, or retain a saved list for later cleanup.
Partial files and checksummed JSON checkpoints use reserved `.fieldforge-partial-`
names inside the maps folder. They are not offline maps. Empty lock files remain
to coordinate retries; OS locks release when the process exits. Checkpoints are
flushed every 8 MiB and on handled interruption. After an abrupt process exit,
the saved prefix is checked and any tail beyond that checkpoint is trimmed before retry.
A damaged/orphaned checkpoint is preserved and requires explicit discard.

Lists hold up to **100 maps**, reject duplicate IDs and portable-filename
collisions, and use the bounded 8 MiB local JSON import. They retain one portal
origin and cannot redirect individual downloads to other hosts. **Save list…**
writes a new local JSON file without overwriting existing files. Save a desktop
list before closing FieldForge if you want to use it after restarting. Clearing
or removing a selection never deletes a downloaded map.

## Local files and portability

The desktop stores its portal settings and downloaded files in `online-maps`
beside the active FieldForge database. Maps live under `maps`; saved route
documents live under `routes`. A completed map retains its catalog metadata,
including attribution, license, coverage, version, and checksum. Route documents
retain their endpoints, complete geometry, directions, source, attribution,
license, and retrieval timestamp.

These files are separate from ordinary household-database backups. Back up the
`online-maps` directory when moving the map/route collection to another device.
Saved place coordinates continue to use the existing waypoint database and its
normal backups. Portal URL settings do not store an account password.

The browser home includes maps, route tools, and reserved sections for the
program's knowledge/download packs. Unpublished sections and proposed tier
allowances are labeled as drafts. See [publishing and package notes](PORTAL_ROADMAP.md).
The browser asks for its own confirmation before API access. **Disconnect**
stops FieldForge's online tools; it does not disable the device's network or
close a browser that has already been opened.

The existing **Navigation → Online map portal…** window also remains available.
It supports choosing an exact destination for a map download and writes a
`.source.json` companion beside that file. Its place CSV and planned GPX exports
remain ordinary local files. Back up those chosen locations separately from the
managed `online-maps` collection.

Inside a place editor, **Find address online…** fills the current editor for
review and preserves its existing notes. Closing the lookup returns to that
editor; the lookup does not press **Save place**. The GPS portal action can fill
the GPS manual-coordinate form, where **Show coordinate** remains a separate
choice. These actions do not create a receiver fix or start recording.

Downloads stream to a temporary or explicitly retained partial file. Wrong lengths, failed checksums, invalid
formats, cancellation, and transport failures do not install a completed map.
Existing files are not silently replaced. A saved route is written as a validated,
versioned local document. GPX export creates a **planned track**, clearly labeled
as planned route geometry; it does not fabricate receiver fixes or trip times.

Supported portal map formats are raster MBTiles, PNG, JPEG, WebP, TIFF, GIF,
BMP, ICO, PPM/PGM/PBM/PNM, TGA, JPEG 2000, and AVIF. The additional image families
use the existing optional image decoder and require the appropriate installed codec.
Raster MBTiles use the existing map reader's supported schema and
image formats. The existing viewer limits are 16 GiB for a raster MBTiles pack
and 64 MiB for a map image, with at most 32 million pixels and a 32,768-pixel side.
Publication and desktop installation apply the same image preflight.
Vector MBTiles, PMTiles, raw OSM PBF, and archive extraction are
not implemented in this portal client. Opening many image formats uses the
existing optional Pillow dependency (`pip install ".[maps]"`). An ordinary
image remains an image reference; downloading it does not calibrate it.

Route JSON documents are limited to 8 MiB, including the saved-file envelope.
Routes retain up to 50,000 geometry points and 10,000 written instructions within
that byte limit. The browser exports compact UTF-8 JSON so its downloaded route
files can be imported by the desktop without expanding beyond the file limit.

## Run a portal locally

From a source checkout:

```bash
python -m fieldforge.online.server --config examples/map-portal.json
```

After installation, `fieldforge-map-portal --config examples/map-portal.json`
is the equivalent entry point. The earlier module command,
`python -m fieldforge.map_portal --config examples/map-portal.json`, runs the
same server. Both module commands accept an optional `--port 8766` override;
without `--config` they start an unconfigured local portal. The example listens
on `127.0.0.1:8765`.
Open `http://127.0.0.1:8765` in a browser, or use that URL in the desktop app.

The browser requires an explicit connection choice before requesting portal
status, maps, addresses, or routes. **Go offline** cancels pending requests and
retains selected coordinates and route downloads. Restored connectivity alone
does not reconnect it. `FIELDFORGE_MAP_PORTAL` can prefill the desktop portal URL;
prefilling a URL does not establish a connection.

The example has an empty catalog and no geocoder/router. It can serve published
map packs, but address search and route requests remain unavailable until the
operator configures those services. Empty configuration does not silently fall
back to a public provider or display fictional worldwide coverage.

`catalog_root` resolves relative to the configuration file. The example uses a
`portal-maps` directory in the repository root; keep operator data outside the
source checkout in production.

### Publish a permitted map pack

The catalog publisher copies a file into immutable storage, computes its size
and checksum, validates its supported format, and records its attribution.

```bash
python -m fieldforge.online.catalog add \
  --root ./portal-maps \
  --file /path/to/permitted-region.mbtiles \
  --id region-overview-v1 \
  --title "Regional overview" \
  --license "License applicable to this map" \
  --attribution "Required source and creator attribution" \
  --source "Actual provider or dataset reference" \
  --coverage "The actual area and detail level covered by this file" \
  --version "2026-10-03"
```

The publisher does not acquire rights to a map. Supply the actual license and
attribution for a file you may distribute. Each catalog entry describes a real
published file, not a promise of complete world or country coverage. Use new
IDs for new immutable pack versions.
The optional `--source` records the map's provider or dataset identity alongside
its license and attribution; `--file` identifies the file to publish.

### Prepare several maps from an inventory

Copy `examples/map-catalog-inventory.json`, replace its example entries with
actual local files and their rights/source information, then run:

```bash
python -m fieldforge.online.catalog build \
  --inventory /path/to/map-catalog-inventory.json \
  --root ./new-portal-maps
```

The installed `fieldforge-map-catalog` command provides the same `build`, `add`
and `list` subcommands. `asset_folder` is relative to the inventory file (or an
absolute local folder). Each `filename` must be a simple basename in that
folder. The example is a template, not a supplied map or permission to publish.

The builder validates and copies every listed map into private staging storage,
calculates sizes and SHA-256, and checks the sources have not changed before
publishing the shared catalog index. A bad file fails the batch without a
partially visible catalog. Source files are not modified. The destination must
be a **new directory**, with an existing parent; even an empty existing directory
is refused. No other files in the asset folder are scanned or published.

The inventory accepts 1–5000 maps within 8 MiB of JSON. Each map uses the same
format limits and immutable publisher as `add`: raster MBTiles up to 16 GiB and
supported image files up to 64 MiB, subject to decoder limits. Metadata must
include a unique ID, title, coverage, version, source, attribution and license.
Images remain reference images unless separately calibrated in an appropriate
workflow; vector MBTiles are not supported by the raster viewer.

Inspect the generated catalog with `list --root ./new-portal-maps`. To serve
it, deliberately update the operator configuration's `catalog_root` and restart
the service. The builder does not replace existing catalogs, alter server
configuration, fetch maps or start an online session.

### Configure address and routing providers

An operator configuration can contain these provider records:

```json
{
  "host": "127.0.0.1",
  "port": 8765,
  "catalog_root": "/srv/fieldforge/maps",
  "public_origin": "https://maps.example.org",
  "providers": {
    "geocoding": {
      "url": "https://geocoder.example.org",
      "name": "FieldForge address search",
      "source": "FieldForge geocoder — https://geocoder.example.org",
      "attribution": "© OpenStreetMap contributors — https://www.openstreetmap.org/copyright",
      "license": "ODbL 1.0"
    },
    "routing": {
      "url": "https://router.example.org",
      "name": "FieldForge driving routes",
      "source": "FieldForge driving graph — https://router.example.org",
      "attribution": "© OpenStreetMap contributors — https://www.openstreetmap.org/copyright",
      "license": "ODbL 1.0"
    }
  }
}
```

The example hostnames are placeholders. Replace them with services the operator
actually runs or is authorized to use. Match the attribution and license to
the underlying data. Provider URLs require HTTPS; explicitly enabled loopback
HTTP is available for local service testing. The desktop accepts HTTPS portal
URLs, with HTTP allowed only for loopback development.

The optional provider `name` is the label displayed on connection and defaults
to its `source`. Request timing and result caching can be configured per provider:

| Setting | Modern `providers` default | Legacy version-1 default |
|---|---|---|
| `minimum_interval_seconds` | `0` (no added request spacing) | `1.1` |
| `cache_ttl_seconds` | `0` (cache disabled) | `600` |

Both settings accept 0–3,600 seconds. Each provider permits one request in
progress per process. When enabled, its process-local cache retains at most
128 results and 16 MiB of serialized result data. Configure any deployment-wide
rate limit at the provider or hosting layer; multiple workers have separate gates
and caches.

The geocoding adapter uses Nominatim's search API. The routing adapter uses
OSRM's driving route API with requested alternatives, full GeoJSON geometry,
and maneuver steps. OSRM's transport profile comes from the data used to build
the router; changing a URL segment does not create walking or cycling coverage.

### Existing portal configurations

Version-1 configurations retain `geocoder`/`router`, `asset_folder`, and inline
`maps`, including their `kind`, `size`, and `updated` fields. They use the same
portal and validation as the modern configuration. Original map files are
verified and served read-only in place; loading a legacy configuration does not
copy files or rewrite the configuration. Prefer `catalog_root` and the catalog
publisher for new deployments.

Before upgrading a legacy configuration, add an explicit `license` to each
configured geocoder and router. Use the actual provider/data license; startup
rejects a missing license because it cannot be inferred from a provider name.

## Operate a public portal

The included Python server is a self-hostable application, not a purchased
hosting account or a deployed worldwide map service. Put it behind a maintained
HTTPS reverse proxy and configure the public origin. Supply capacity, request
limits, access control if needed, backups, storage, and actual regional data at
the hosting layer. The application is deliberately read-only over HTTP: map
publication is an operator CLI operation, not an anonymous upload endpoint.

Set `public_origin` to the exact external HTTPS origin, such as
`https://maps.example.org` or `https://maps.example.org:8443`, and preserve its
host and any nondefault port in the forwarded `Host` header. Host the portal at that
origin's root; a URL subpath is unsupported. A rewritten upstream host can cause
the portal's Host/Origin checks to reject browser requests.

Both hosts serve single byte ranges on map `/download` and legacy `/file`
endpoints. Forward `Range` and `If-Range` through the proxy and preserve
`Accept-Ranges`, `ETag`, `Content-Range` and `Content-Length` on responses.
Serve map bytes without compression or transformation. The strong ETag is the
catalog SHA-256. Valid ranges return 206; unsatisfiable ranges return 416 with
the full map length. A changed/weak If-Range tag returns the full 200 response;
unknown units or multipart range lists are ignored and receive the full file.
The desktop checks these headers before appending to its own partial file.
See [HTTP conditional range semantics, RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.5).

For an existing WSGI deployment, the compatible entry point is:

```python
from fieldforge.map_portal import create_app

application = create_app("/etc/fieldforge/map-portal.json")
```

The WSGI host and reverse proxy must bound incoming header/body reads, concurrent
requests, and request runtime, including clients that send data slowly.
`request_timeout_seconds` limits provider requests, not incoming WSGI reads.
The included native server has a 15-second socket timeout and a 16-request
worker bound; retain the public hosting controls when using it behind a proxy.

The desktop sends a submitted address or chosen route coordinates to this
portal; the portal forwards that request to the configured provider. The server
does not write address/query access logs itself. Configure proxy and provider
logging with this data flow in mind. No service credentials should be embedded
in a distributed desktop application.

## Provider references and implementation decisions

- [Nominatim search API](https://nominatim.org/release-docs/latest/api/Search/)
  documents free-form address queries and coordinate results.
- [OSMF public Nominatim policy](https://operations.osmfoundation.org/policies/nominatim/)
  imposes app-wide limits, identification, and other restrictions on its public
  server. FieldForge has no hidden public-geocoder default.
- [OSRM route API](https://project-osrm.org/docs/v5.24.0/api/) describes
  alternatives, full route geometry, steps, and profile behavior.
- [OSRM demo-server policy](https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server)
  limits the public demonstration service. It is not a commercial backend default.
- [OSMF tile policy](https://operations.osmfoundation.org/policies/tiles/)
  prohibits offline tile scraping/prefetch from the public standard tile service.
  The portal serves prepared files from its own catalog instead.
- [OpenStreetMap data license](https://www.openstreetmap.org/copyright) and
  [Natural Earth terms](https://www.naturalearthdata.com/about/terms-of-use/)
  are relevant starting points for permitted data production. Neither link
  means that its datasets are already installed in this repository.

Future work includes operating the public portal, adding licensed US-first and
then worldwide map coverage, regional routing graphs for genuine offline
recalculation, walking/cycling providers, and independent mobile application
packaging. This implementation extends the current desktop application and
adds a browser portal; it does not claim finished Android or iOS native apps.
