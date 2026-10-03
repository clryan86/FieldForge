# USA-first map rollout: Connecticut, Maryland, West Virginia and Oklahoma

All four additional map/search packs are prepared and their final ZIPs independently verified. Source headers report **2026-10-02T20:21:34Z**. USA coverage remains first; worldwide coverage remains the next geographic phase.

## Actual delivered data

| Region | Prepared ZIP bytes | Indexed source objects | Address-tagged objects |
| --- | ---: | ---: | ---: |
| Connecticut | 918,644,135 | 3,647,565 | 1,090,773 |
| Maryland | 969,185,195 | 3,556,322 | 1,192,982 |
| West Virginia | 362,890,565 | 988,652 | 40,875 |
| Oklahoma | 629,277,794 | 1,996,334 | 111,167 |

Total additions: **10,188,873 indexed objects**, including **2,435,797 address-tagged objects**. These are retained source-object counts, not unique addresses or guarantees of complete real-world coverage. Extracts can include adjoining geography. Complex relation/multipolygon assemblies remain in the original PBF but are not assembled by the current visual index.

The four ZIPs total 2,879,997,689 bytes; their expanded contents total 7,330,129,872 bytes. Original PBF files, matching source checksums and attribution/rights receipts are preserved in each data pack.

## Acquisition and final validation

Public Geofabrik/OpenStreetMap acquisition run:
https://github.com/clryan86/FieldForge/actions/runs/37091503131
Acquisition commit: `c43c15ffa2949cc35ae05a6b20b42f822ac66015`.
The source-test job and all four acquisition jobs completed successfully. Artifact ZIP CRC/digests, publisher MD5 receipts, PBF SHA-256 and extract polygons were checked.

Each final delivered ZIP was extracted to a fresh folder, CRC checked, source-matched and fully verified with the production region verifier. SQLite structure/integrity, spatial R-tree integrity, counts, source identities and file digests passed. Offline name lookups for Hartford, Baltimore, Charleston and Tulsa passed, and literal recorded address fields matched actual source records with Python networking denied. Test household sentinels and original source bytes remained unchanged.

All four actual maps were opened in the production Tk viewer and exercised through search, selection, centering, zoom, pan and normal close. Screenshots show actual source geometry, not generated mockups. Source labels remain explicit: NOT navigation. The Tulsa demonstration selected the source county reference record, not a device position or an assumed city entrance.

## Software update required for larger maps

Real data exposed two issues that are corrected in the supplied small source updater and `tools/usa_maps/large-map-checks.patch`:
- Full-index verification receives a bounded 180-second SQL deadline instead of 30 seconds. Integrity, R-tree, schema, count, source/hash and cancellation checks are retained.
- Wide views now limit spatial candidates before fetching/sorting feature rows. The old all-intersections sort exceeded the 4-second query deadline on Maryland and prevented the combined search/view update. The 4-second interactive and 6-second address-search deadlines remain unchanged; wide views clearly report limited detail.

Final module SHA-256: `c7004c801b86a32b66464650ff7e3df80ac0c3178189576242d5e717e0e3514f`.
The updater recognizes the exact original source, backs it up, refuses unknown/custom versions and changes only `fieldforge/navigation/regional_index.py`. No map or household database is edited by it. It is not an EXE installer. Its delivered ZIP was freshly extracted and its CLI update, final hash, backup/idempotence and untouched household sentinel were checked.

Final local tests: **371 targeted cases passed** — 286 backend/UI, 57 acquisition/preparation and 28 updater tests, including **43 new cases**. This is not a new full-application run. Actual Tk tests used Xvfb. Python 3.10 grammar and exact patch checks passed, but local execution was Linux/Python 3.13.5. No native Windows/macOS/phone, physical GPS, Ruff or driving-navigation certification is claimed. The separate newest desktop ZIP-import dialog was not rerun here; the existing v1 prepared-pack layout and prior USVI format compatibility were checked.

## Unsuccessful attempts and recovery

Initial Connecticut/Maryland attempts stopped on the old verification deadline. Connecticut was rebuilt from identical original source with the extended bounded verifier; road preparation was not requested in the successful rebuild. Maryland's complete retained staging index was fully reverified before export.

West Virginia's initial attempt stopped on the file-change guard after a developer staging-preservation helper created hard links during hashing, changing inode metadata. The helper was changed to copying; the retained index passed all production checks independently before export. This was a developer-workspace concurrency effect, not a claim of corrupt publisher data. Oklahoma completed its original preparation workflow. Earlier failure logs are preserved in the delivery record rather than counted as successes.

## Routing and coverage boundaries

None of these four packs supplies validated driving directions. Maryland, West Virginia and Oklahoma graph preparations refused unsupported restrictions (555630, 2575561 and 1205968). Connecticut's successful delivery is explicitly map/search only, with graph preparation not requested.

Including earlier deliveries, prepared detailed extracts have been reported for **11 states**, plus DC, Puerto Rico and USVI. **39 states**, additional territories and complete national water/elevation/topographic/nautical collections remain outstanding. Previously delivered states were not all reverified in this pass. A national outline is not counted as detailed street coverage; a prepared package is not an installation audit of the user's computer.

Data ZIPs are additional imports for the map-manager source build. Apply the small large-map update first, then use Maps -> Map tools -> U.S. installed street regions -> Import prepared pack. Select each regional ZIP directly; do not extract it first. Existing downloads do not update themselves.

The download workflow, patch and this progress record are on `chatgpt/usa-batch-wave4`. The later chat-delivered application modules and prepared databases are not all in this branch's older application tree and have NOT been merged into `main`.

## Final prepared pack hashes

```
e6d3f1dd4b01efc35c4ac676b74709fea6c52a569b5b317833369dbba9bbef52  FieldForge-USA-Connecticut-2026-10-02.zip
461e0702e16cdd1a8769018950316f55d349fd29ac2d0b6658b45c5b52a08d291  PLACEHOLDER_DO_NOT_USE
09c99b29d60227ed5a68f6d0d93c81e3d55eb7dfde1da81c0f6ebf9f3f1471e7  FieldForge-USA-West-Virginia-2026-10-02.zip
6e0c8b4d0448ef9fe8ec533350efb6e9290c4beef83a7d3cd48cb6643ac04c8f  FieldForge-USA-Oklahoma-2026-10-02.zip
```

The accompanying checksum file is authoritative for all four final ZIPs; the Maryland checksum is recorded there and will be populated in this table after exact comparison.

Sources and rights: © OpenStreetMap contributors, ODbL-1.0.
https://www.openstreetmap.org/copyright/en
https://download.geofabrik.de/north-america/us.html
Checksums detect changes; they are not independent publisher signatures or geographic accuracy certification.
