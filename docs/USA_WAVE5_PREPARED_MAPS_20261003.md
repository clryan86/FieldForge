# USA map rollout: North Dakota, South Dakota, Nebraska and Kansas

Four additional prepared map/search ZIPs were built and verified from real Geofabrik/OpenStreetMap extracts. Every original PBF reports snapshot **2026-10-02T20:21:34Z**. USA coverage remains first; worldwide coverage remains phase two.

## Prepared data actually delivered

| Region | ZIP bytes | Expanded bytes | Indexed source objects | Address-tagged objects |
| --- | ---: | ---: | ---: | ---: |
| North Dakota | 412,751,587 | 850,043,980 | 1,079,277 | 10,740 |
| South Dakota | 194,212,607 | 433,708,775 | 626,562 | 17,522 |
| Nebraska | 433,700,647 | 1,061,169,388 | 1,560,326 | 127,499 |
| Kansas | 517,561,706 | 1,300,038,097 | 1,960,601 | 215,066 |

Totals: **5,226,766 indexed objects**, **370,827 address-tagged objects**, **1,558,226,547 compressed bytes** and **3,644,960,240 expanded bytes**. Counts are retained source objects, not unique addresses or guarantees of complete real-world coverage. Extracts can include adjoining geography. The current viewer does not assemble complex relation/multipolygon features; their source records remain in the preserved PBF.

Each pack includes the original PBF, source/rights receipts, a checked searchable map index and separate map/road availability. These are prepared downloads, not an audit of what is installed on the user's computer.

## Acquisition and actual verification

Acquisition run: https://github.com/clryan86/FieldForge/actions/runs/37095186139
Commit: `82e1f199d5518a508da2424cff2af116b8579a67`.
The source-test job and all four bounded acquisition jobs completed successfully. Retrieved artifact ZIP SHA-256/CRC, publisher MD5, source SHA-256 and polygon receipts were checked.

Every final prepared ZIP was freshly extracted using its fixed allowed member list, CRC checked and verified with the production region verifier. SQLite/spatial integrity, schemas, counts, source/index identities and member hashes passed. Original PBF bytes matched the acquired sources. Actual offline name searches for Fargo, Sioux Falls, Omaha and Wichita succeeded; queries using source-recorded house-number/street fields returned the selected source object in every region. Network socket creation was forbidden and private test database sentinels remained unchanged.

Independent GDAL/pyogrio spot checks matched **119 line geometries** to the source coordinates (30 ND, 29 SD, 30 NE, 30 KS; 1e-8-degree tolerance). This is not a full-map geographic accuracy audit.

All four actual Tk maps opened the final-ZIP data and exercised search, selection, centering, zoom, pan and normal closing. Final screenshots select source city reference points, not GPS positions or road destinations. The initial screenshot harness used the wrong delimiter for place kinds and selected the first substring match; only the harness was corrected, then all four checks were repeated with exact city selections.

## New code: offline map collection checker

`tools/usa_maps/catalog.py` verifies explicitly selected prepared ZIPs and writes a portable JSON receipt. It refuses duplicate case-insensitive filenames, repeated region IDs/source snapshots, changed inputs, unsafe links and overwrites. Atomic no-clobber publication uses a flushed temporary file and hard link; unsupported filesystems fail. It makes no network or household-database calls.

Every entry explicitly states `status=verified-download`, `installed_on_device=not-checked`, and `validated_navigation=false`. The receipt contains metadata, not maps; it is neither a USA installer nor an installation audit. Existing installs are not modified. See `tools/usa_maps/COLLECTIONS.md`.

**23 new tests** were added. Local tool tests: **80 passed**, including the actual synthetic prepared-pack integration. Existing targeted regional-index/install/location-search backend and Tk tests: **271 passed**. Total local targeted cases: **351**, not a new full-application run. An initial aggregate tool invocation timed out before completion; the complete supervised rerun returned exit code zero and is the run counted here.

Published tool/source commit: `80f3ea5a14c94413ccacfc59e513e662b767fdfc`.
CI: https://github.com/clryan86/FieldForge/actions/runs/37095556002
Both Linux Python 3.10/3.12 check jobs and the source-archive job passed. The older repository tree lacks the separate regional backend, so the single backend integration case skips remotely and passed locally. Downloaded final Python tool/test bytes matched the locally tested bytes, and all 80 local tool tests were repeated on the published copy. The actual collection checker reverified all four REAL final ZIPs and its totals/digests matched the independent delivery checks.

## Backend and integration boundaries

The newest full map-manager ZIP was not available here. Local backend source was reconstructed from the CRC-checked complete regional-installer archive plus the checked USA-first patch. All 96 Python modules matched independently recoverable CRC-checked entries in the earlier truncated first-data archive. That truncated archive was not redistributed as an app.

The already-published wave-four large-map patch was applied. Final `regional_index.py` SHA-256: `c7004c801b86a32b66464650ff7e3df80ac0c3178189576242d5e717e0e3514f`. It retains bounded 180-second full verification, 4-second interactive and 6-second address-query deadlines. Older source installations need the documented large-map update; its exact patch is included in the developer tools.

The newest desktop ZIP-import dialog was not re-executed in this pass. These ZIPs retain the existing region-install-v1 prepared-pack layout. No new full desktop package, native Windows/macOS/mobile, physical receiver, browser, Ruff, live closure, ETA or validated driving-navigation check is claimed.

## Routing and outstanding coverage

All four road-graph preparations refused unsupported restrictions instead of discarding them: North Dakota 4857047, South Dakota 3419293, Nebraska 1902727 and Kansas 2714796. **These maps are for viewing/searching, not driving directions.** No cross-state routing claim.

Earlier wave-four records report 11 states (DE, NJ, RI, HI, VT, NH, ME, CT, MD, WV, OK), plus DC, PR and USVI. Those earlier files were not all reverified this turn. With the new four, the recorded prepared-state total is **15**; **35 states** remain, plus additional territories and complete national topographic/water/nautical collections. Nationwide outlines are not detailed-street coverage.

In the compatible updated map-manager source build, use Maps -> Map tools -> U.S. installed street regions -> Import prepared pack. Select each regional ZIP directly; do not extract it first. This remains a one-time explicit import, not automatic installation on the user's machine. Keep both adequate download/import storage and separate map backups.

## Final ZIP hashes

```
c5cdcac1dd5eed560fc218dc120f270505836cc976aadaf2f43c62681ff9d6d4  FieldForge-USA-North-Dakota-2026-10-02.zip
66c2a7ed66ab3c37a770db097038513670254e6f73878142cb0503288c3f324e  FieldForge-USA-South-Dakota-2026-10-02.zip
6cb6e612f048ef398a370560280eada90b6b3b7e6ec7da63f954f499477c84ae  FieldForge-USA-Nebraska-2026-10-02.zip
c3d436b923c423301bfb0ed54c00bac1bc72feefeb455a225a8cf493a94cc778  FieldForge-USA-Kansas-2026-10-02.zip
```

Code/workflow/tests and this record are on `chatgpt/usa-batch-wave5-20261003`. Main and concurrent desktop branches were not modified. Prepared data files are separate chat downloads, not Git-tracked application assets. CI artifacts expire after 14 days; keep local copies. Checksums are unsigned integrity checks, not publisher signatures or safe-travel certification.

Source and rights: © OpenStreetMap contributors, Open Database License 1.0.
https://download.geofabrik.de/north-america/us.html
https://www.openstreetmap.org/copyright
