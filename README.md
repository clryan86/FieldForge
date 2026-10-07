# FieldForge

**FieldForge is an offline-first emergency preparedness and survival operations system.**

It is designed to remain useful when the internet, cloud services, cellular networks, or normal infrastructure are unavailable. The project combines local planning tools, resource calculations, household readiness, emergency checklists, an offline knowledge library, and optional online map preparation in one auditable desktop application.

> FieldForge is a preparedness and reference tool. It does not replace emergency services, licensed medical care, official evacuation orders, or professional advice.

> The map features below describe tested local integration `fe70c8b`.
> Publication to the shared development branch is pending. See
> [map integration status](docs/MAP_INTEGRATION_STATUS.md) for verified behavior,
> remaining checks, and the source/data publication boundary.

## Design principles

- **Offline first:** core features require no network connection.
- **Local ownership:** user data lives in a local SQLite database.
- **No account required:** no login or cloud dependency.
- **Auditable calculations:** water, food, power, fuel, and readiness estimates expose their assumptions.
- **Graceful degradation:** the program remains useful with only Python's standard library.
- **Portable data:** export/import support is part of the architecture, not an afterthought.
- **Safety before novelty:** high-stakes guidance is clearly bounded and source-aware.
- **Useful under stress:** emergency actions should be easy to find, prioritize, print, and execute.

## Planned capabilities

### Emergency operations
- Household emergency dashboard
- Incident log and priority action queue
- Scenario plans for blackout, severe weather, evacuation, vehicle stranding, lost-person situations, and infrastructure disruption
- Rendezvous points, emergency contacts, vehicles, and evacuation destinations

### Supplies and logistics
- Food, water, fuel, medications, batteries, tools, and consumables inventory
- Expiration and replacement tracking
- Water-consumption and storage projections
- Food/calorie runway estimates
- Battery, inverter, generator, solar, and appliance runtime calculations
- Go-bag and vehicle-kit readiness scoring

### Offline knowledge
- Searchable local field-guide library
- Topic tags, bookmarks, favorites, and notes
- Source/provenance metadata
- Printable emergency reference sheets
- Local full-text search without an internet connection

### Navigation and mapping
- Coordinates, distance, bearing, and waypoint tools
- Included U.S. overview atlas with 615 tiles and 777 selected town reference points
- Local flat/normalized raster MBTiles, basic vector previews, and image-map viewers
- Optional online address lookup to fill saved places and route endpoints
- A configurable map portal with verified map downloads and saved route alternatives
- Read saved directions offline, show planned-route overlays, and export GPX
- Additional world map coverage and offline rerouting remain future work

### Privacy and resilience
- SQLite local database
- JSON backup/export format
- Integrity checks
- Future optional encrypted personal vault
- No telemetry in the core application

## Architecture

```text
fieldforge/
  core/          domain models, validation, readiness logic
  db/            SQLite schema, migrations, repositories
  planners/      water, food, power, evacuation and kit calculators
  scenarios/     scenario definitions and action generation
  knowledge/     offline guide/search engine
  navigation/    geospatial helpers and map-pack interfaces
  ui/            desktop UI
  cli.py          command-line interface
  app.py          application service layer

tests/
knowledge_base/
docs/
```

The core planning and reference features avoid internet APIs. The separate `fieldforge.online`
package contacts only a configured portal after the user chooses to connect. Optional
integrations are not required for emergency operation.

## Initial development milestones

### v0.1 — survival core
- [ ] SQLite data model and migrations
- [ ] Household/member profiles
- [ ] Inventory CRUD
- [ ] Water runway calculator
- [ ] Food/calorie runway calculator
- [ ] Power-runtime calculator
- [ ] Go-bag readiness model
- [ ] Emergency scenario/action engine
- [ ] JSON backup and restore
- [ ] CLI
- [ ] Automated tests and CI

### v0.2 — field interface
- [ ] Offline desktop dashboard
- [ ] Inventory and planner screens
- [ ] Incident mode
- [ ] Large-text / low-light emergency mode
- [ ] Printable emergency sheets

### v0.3 — offline knowledge
- [ ] Local field-guide corpus
- [ ] Full-text search
- [ ] Bookmarks and field notes
- [ ] Source/provenance display
- [ ] Search from desktop UI

### v0.4 — navigation
- [ ] Waypoints and rendezvous points
- [ ] Distance/bearing tools
- [ ] Offline map-pack interface
- [ ] Route export/import

## Status

FieldForge is under active construction. The first goal is not a flashy demo; it is a dependable offline core with tests, reproducible calculations, durable local storage, and a clean path to a full desktop application.

## Included atlas and local map viewers

The tested integration includes a **615-tile U.S. overview atlas** and **777 selected
town reference points** from Natural Earth. These application resources open
offline without a download or manual import. The overview shows generalized
land, state outlines, selected city labels, rivers and lakes. It has no street
detail or terrain elevations, and the town catalogue is not a complete
settlement or address directory.

In **Maps**, choose **Included U.S. atlas…** for the lower 48 states, Alaska,
Hawaii, or the listed U.S. territory views. Choose **Find included U.S. towns…**,
search by town or state, select a result, and choose **Show selected town on
included atlas**. This opens the atlas with a temporary reference marker.
**Clear town marker** removes it; no saved waypoint is created.

**Navigation → Maps, GPS & places…** opens the combined receiver, local-map,
offline-place and saved-trip workspace. Its **Included U.S. atlas…** button opens
the same overview. Use **Find places / coordinates… → Included U.S. towns**, then
**Show selected place on map** to center a reference point on the current map or
coarse outline. These actions do not connect a receiver or record a trip.
See [GPS workspace](docs/GPS_WORKSPACE.md).

**Maps → Open local map…** reads supported local PNG/JPEG/WebP MBTiles in flat
or normalized `map`/`images` storage. Both map viewers also display
gzip-compressed MVT/PBF tiles with a basic preview style and bounded embedded-name
labels. Arbitrary view-based layouts and publisher styles, fonts and sprites
remain unsupported. The portal's MBTiles publisher still requires flat indexed
packs; local normalized-file support does not expand publication compatibility.

**Navigation → Open map image…** opens local images as uncalibrated references.
Source installations use `pip install ".[maps,gps,pdf]"` for image, receiver and
PDF support. External maps and image files need separate backups.

The separate **Prepared regional map…** viewer opens local `.ffmap` indexes,
imports the index from a supported regional ZIP, and offers **Prepare PBF…**
for a local OSM source. These display/search indexes do not calculate routes.
No complete U.S. street database or offline routing engine is bundled.
See [Offline Maps](docs/OFFLINE_MAPS.md) for formats, coverage and preparation.

## Prepare maps and routes online, use them offline

Open **Online Maps**, or **Navigation → Online maps, addresses & routes…**.
Enter the address of an operated FieldForge portal and choose **Connect**.
The application starts disconnected and does not submit addresses while typing.

- **Address search:** submit an address, choose the intended match, then copy its
  latitude/longitude, fill a saved-place editor, center a local map, or fill a route endpoint.
  **Find address online…** in an open place editor fills that editor for review;
  **Navigation → Online map portal…** also preserves the GPS coordinate-form handoff.
  Selected coordinates can be saved as CSV for the offline place catalog.
- **Map downloads:** browse the portal's actual catalog, review coverage, format,
  size and attribution, and download a selected map. Completed files are checked
  against the catalog's byte count and SHA-256 checksum before installation.
- **Routes:** request driving-route alternatives, inspect the directions, and save
  a selected route locally. Reopen saved directions, show the planned route over
  a local MBTiles map, or export its geometry as GPX after disconnecting.
  Routes downloaded from the browser portal can also be imported while offline.

This repository includes the **portal server and browser interface**, with adapters
for an operator-configured Nominatim geocoder and OSRM driving router. It does
not provision a public website, contain all world maps, or provide a default
public geocoding/routing account. A portal operator must supply permitted map packs,
hosting, and provider data. New route calculation and address lookup require a
connected configured provider. Saved directions, planned geometry and GPX export
remain available after disconnecting; new offline route calculation, live traffic
and automatic offline rerouting are not implemented. See [Online map portal](docs/ONLINE_MAP_PORTAL.md) for setup,
file locations, supported formats, and the online/offline boundary.

## Windows development application

The Windows build workflow is configured to produce a **FieldForge-Windows-x64**
archive with Python, Tk, Pillow image codecs, the serial adapter and the PDF
text parser. Windows execution of this integration remains pending; the headless
checks in [map integration status](docs/MAP_INTEGRATION_STATUS.md) do not establish
a verified Windows release. Extract the entire folder and run **FieldForge.exe**; no separate
Python installation is needed for this edition. The GUI and PDF-worker helper
are separate executables so packaged PDF extraction and recovered-window launch
use the correct process entry points. **Help → Build & data location** identifies
the build and database in use. This is unsigned development software, not a
signed installer or automatic updater. See [Windows portable build](docs/WINDOWS_PORTABLE.md)
for data locations, the recovery launcher, verification scope and update steps.

## Offline places and bearings

**Places** manages saved waypoints and private notes, calculates approximate
point-to-point distances/initial true bearings, and previews GPX 1.1 waypoint
imports/exports. No maps, live GPS, magnetic correction or safe routes are implied.
GPX exports disclose precise coordinates; private notes are excluded unless
explicitly selected. See [Places & GPX](docs/PLACES_AND_GPX.md) for limits,
conflict handling, privacy and full-backup compatibility.

## Original PDF preservation

**Knowledge Library → Original PDFs…** stores unchanged local PDFs (including
scans and diagrams) independently of text extraction. Optionally associate a file
with the open article, verify its stored bytes, and export a new byte-identical
PDF for your own viewer. Nothing opens automatically. Full SQLite backups include
these originals; article JSON/HTML exports do not. This is unencrypted storage,
not a malware scanner, PDF renderer or source-review service. See
[Original PDFs](docs/ORIGINAL_PDFS.md) for limits and the separate capture/consent step.

## Bundled Foundations learning pack

**Knowledge Library → Foundations Pack…** contains 20 original lessons and 40
self-check exercises on practical mathematics, measurement, stock planning and
records. Read/practice before installing; **Add missing lessons to Library**
adds searchable articles without replacing edited copies or private notes.
The original AI-drafted lessons are not independently specialist-reviewed.
See [Foundations pack](docs/FOUNDATIONS_PACK.md) for content, compatible JSON
imports, worked answers and the distinction between exercises and qualifications.

## Portable Pocket Library

In the desktop Knowledge Library, use **Pocket Reader…** to export the open
article or your bookmarked articles as a phone-friendly, self-contained HTML
reading copy. It offers local search and category/reading-size controls in
compatible browsers, with static full text as a no-script fallback. Private
article notes are always excluded. This is a read-only export, not a native
mobile app or the complete reference corpus. See [Pocket Library](docs/POCKET_LIBRARY.md)
for device/file-opening limitations, size bounds and privacy details.

## License

A project license will be selected before the first release.
