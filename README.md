# FieldForge

**FieldForge is an offline-first emergency preparedness and survival operations system.**

It is designed to remain useful when the internet, cloud services, cellular networks, or normal infrastructure are unavailable. The project combines local planning tools, resource calculations, household readiness, emergency checklists, an offline knowledge library, and eventually downloadable map packs in one auditable desktop application.

> FieldForge is a preparedness and reference tool. It does not replace emergency services, licensed medical care, official evacuation orders, or professional advice.

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
- Offline map-pack interface planned for a later milestone
- Exportable routes and rendezvous points

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

The core package intentionally avoids internet APIs. Optional integrations must never be required for emergency operation.

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

## Offline raster map viewer

**Maps → Open local map…** reads compatible, already-local PNG MBTiles packs
with pan/zoom and an optional saved-place overlay. Missing/corrupt tiles are
labeled; no map tiles are downloaded and no GPS or safe-route guidance is implied.
This first viewer supports flat indexed PNG packs, not JPEG/vector or view-based
layouts. External map files are **not included in database backups**. See
[Offline Maps](docs/OFFLINE_MAPS.md) for formats, limits, privacy and separate backups.

## Windows development application

The CI-produced **FieldForge-Windows-x64** archive bundles Python, Tk and the PDF
text parser. Extract the entire folder and run **FieldForge.exe**; no separate
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
