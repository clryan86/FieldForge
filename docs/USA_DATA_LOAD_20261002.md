# USA-first data load — 2026-10-02 local date

USA coverage is the first geographic priority. Worldwide coverage remains phase two. See issue #9: https://github.com/clryan86/FieldForge/issues/9

## Successful source acquisition
The data-only workflow completed successfully:
https://github.com/clryan86/FieldForge/actions/runs/37083847495

Acquisition commit: `db871fdf7299850d81d2e9d2d1eab20f855f5a24`.
Artifact `11260255751`, SHA-256 `4c05f42f99e5522eda8553313ddb0315bdeaaf252e08d4b0100c935162fe84ae`.
The artifact was downloaded to the development environment, its ZIP CRC checked, and each original source file matched to its recorded size and SHA-256.

Six sources, 97,751,099 original bytes:
- Census 2025 national state cartographic boundaries.
- Census 2025 national county cartographic boundaries.
- Census 2025 national places Gazetteer.
- Census 2025 national primary roads, not all streets.
- Geofabrik/OpenStreetMap Delaware extract, source replication 2026-10-02T20:21:34Z.
- Geofabrik/OpenStreetMap Washington DC extract, same replication timestamp.

## Local preparation and verification, NOT yet application changes on this branch
The latest chat-delivered regional-installer source checkpoint was used locally, preserving its existing maps and data. It is ahead of this branch's application files; this document must not be mistaken for a merge of that implementation.

The local USA atlas contains 56 state/territory boundaries, 3,235 county-equivalent records, 17,500 primary-road source records and 32,350 Census place reference points. Two newly rendered reference layers add 4,514 tiles. Source identifiers were independently compared with Fiona, all Gazetteer names/coordinates checked against the original text, and all 7,329 combined atlas PNG tiles decoded.

Delaware's searchable local map contains 346,908 features, including 58,749 address-tagged features. DC contains 362,429 features, including 140,368 address-tagged features. These are counts of retained source objects, not unique addresses or guarantees of completeness. Original PBF files and ODbL notices are preserved. Name and source-recorded address lookup were exercised offline in both regions.

Both experimental road graphs are UNAVAILABLE: Delaware encountered conditional/exception/mode-specific restriction 971644; DC encountered unsupported restriction members in 1580278. The builder stopped rather than discard restrictions. These are usable visual/search map indexes, NOT validated driving directions.

The final local regression run after the required tag/reference bounds and menu changes: 2,314 passed and 15 existing optional browser tests skipped, under Linux/Python 3.13.5/Tk. The new test file adds 22 cases. Installed-wheel verification matched all 96 Python modules and verified/queried the actual new data. Native Windows, macOS, phone and physical GPS tests were not performed.

## Coverage still outstanding
Most states' detailed street extracts, additional territory data, complete national water/topographic/elevation/nautical collections, minor outlying islands, real graph support and cross-state routing remain outstanding. The Census Gazetteer covers 50 states, DC and PR; the other island areas have boundary records but are not included in that Gazetteer. A state outline is never counted as detailed street coverage.

The local source ZIP will carry full source receipts and a per-state/territory coverage table. The acquisition workflow and this note are committed here. The new application code, prepared databases, and generated local delivery have NOT been merged into main or published as a finished national navigation release.

Sources:
https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.2025.html
https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.2025.html
https://www2.census.gov/geo/tiger/TIGER2025/PRIMARYROADS/
https://download.geofabrik.de/north-america/us.html
https://www.openstreetmap.org/copyright
