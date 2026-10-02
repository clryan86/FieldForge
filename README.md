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
- [Bundled reference library](docs/REFERENCE_LIBRARY.md): 267 attributed articles across 14 categories, available without downloads
- [Three AI blueprint makers](docs/BLUEPRINT_MAKERS.md): engineering designs, project guides, and software architecture using optional local models
- Iterative AI refinement, portable project history, change comparisons and restore without deleting earlier revisions
- User-owned acceptance limits for dimensions, schedules and components, recomputed independently of model critique
- Offline source preview and passage-level evidence ranking with repeatable retrieval regression measurements
- Engineering assembly views, isometric wireframes, dimensioned part sheets and offline parts/materials CSV exports
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
- [Full local backup and restore](docs/FULL_BACKUP.md) for the complete database
- [Offline evidence retrieval](docs/OFFLINE_EVIDENCE.md) with cited passages from installed articles
- [Optional local AI drafts](docs/LOCAL_ASSISTANT.md) using an installed Ollama model with cloud features disabled
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
  blueprints/    structured design generation, checks, diagrams and exports
  content/       attributed offline reference pack
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

## License

A project license will be selected before the first release.
