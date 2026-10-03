# USA map rollout — wave six

USA remains the first geographic priority; worldwide coverage remains phase two (issue #9).

## Prepared data actually verified

Four additional Geofabrik/OpenStreetMap state extracts were acquired by the repository workflow and converted locally into FieldForge's prepared offline map/search format. All four source PBF headers report snapshot **2026-10-02T20:21:34Z**.

| Region | Prepared ZIP bytes | Expanded bytes | Indexed source objects | Address-tagged objects |
| --- | ---: | ---: | ---: | ---: |
| Alabama | 619,000,060 | 1,377,556,206 | 1,936,144 | 116,058 |
| Arkansas | 436,843,059 | 1,110,780,391 | 1,525,909 | 304,287 |
| Iowa | 554,808,471 | 1,281,732,493 | 1,800,568 | 112,131 |
| Mississippi | 351,688,682 | 798,000,800 | 1,083,996 | 145,098 |

Totals: **6,346,617 indexed source objects**, **677,574 address-tagged objects**, **1,962,340,272 compressed bytes**, and **4,568,069,890 expanded bytes**. Counts are retained source objects, not unique addresses or guarantees of complete real-world coverage.

Every prepared pack preserves the original PBF and ODbL attribution/source evidence. Each completed preparation invokes the production region verifier before accepting the ZIP. The final four-pack collection checker then reverified all ZIPs and recorded `status=verified-download`, `installed_on_device=not-checked`, and `validated_navigation=false`.

Offline searches against the actual final indexes returned recorded source objects for Montgomery, Little Rock, Des Moines, and Jackson. `missing_node_ways` is zero for all four packs.

## Acquisition

Workflow run:
https://github.com/clryan86/FieldForge/actions/runs/37126488440

Acquisition workflow commit: `6fc24ab4cb94020723020f09277dc7e9e210ce38`.

The source test job and all four state jobs completed successfully. Acquisition uses the existing bounded allowlisted downloader, records source hashes and publisher evidence, verifies a saved snapshot before artifact publication, and does not touch household data or device locations.

## Real-data compatibility fix

Alabama exposed a valid OSM entity containing more tags than the older regional reader's 128-tag per-entity safety bound. The reader did not silently skip the entity; preparation stopped.

Wave six adds `tools/usa_maps/tag-limit-512.patch`. It raises only that finite per-entity ceiling to 512 and adds a regression that parses a valid >128-tag entity while preserving explicit bounded failure when the configured cap is lower. The local patched backend's `tests/test_osm_source.py` passed after the change. The patch is intended for the compatible chat-delivered regional map-manager source checkpoint; GitHub's older application tree does not yet contain that backend.

## Verification

A focused local Linux/Python 3.13.5 run completed **368 tests** across OSM parsing, regional indexing, prepared-pack installation, offline location search, acquisition/provider-date tooling, preparation, and collection verification.

The final four-pack collection receipt reports:

- 4 verified downloads
- 1,962,340,272 compressed bytes
- 4,568,069,890 expanded bytes
- 6,346,617 indexed objects
- 677,574 address-tagged objects

A broader full-suite invocation was started but exceeded the execution window before completion; it is **not** counted as a passing full regression run. No native Windows/macOS/mobile, physical GPS, live closure, ETA, or driving-navigation certification is claimed by this milestone.

## Routing status

Road preparation was deliberately **not requested** for this wave. These four packs are **offline view/search data, not driving directions**. This avoids representing an untested road graph as navigation-ready while restriction-model work remains outstanding.

## Coverage status

Earlier recorded detailed state deliveries cover 15 states. Adding Alabama, Arkansas, Iowa, and Mississippi brings the recorded detailed-state total to **19 states**, plus DC, Puerto Rico, and USVI. **31 states remain**, along with additional territories and complete national topographic, water, elevation, and nautical collections.

National outlines and primary highways do not count as detailed street coverage. A prepared download is not proof that a pack is installed on a user's computer.

## Final prepared-pack SHA-256

```text
923c86ef4f15e7e2849e01d57b2e9925c79d3c53858b956cafd4eccabd8b429a  FieldForge-USA-Alabama-2026-10-02.zip
b3faecc6bb3f9af512741190c3119694d5527211f8fd051a11c9fb7f4a334b92  FieldForge-USA-Arkansas-2026-10-02.zip
6b9b3acb8e9e6116d3465180ffebb211ee6924bf0ac544ccd95e7710fffdcc43  FieldForge-USA-Iowa-2026-10-02.zip
74cc59cba44347e1e65601aa0a9a05f7fce4aa2e3abda498554114e5f8ce49c9  FieldForge-USA-Mississippi-2026-10-02.zip
```

Checksums are unsigned integrity records, not publisher signatures or geographic/safety certification. Map packs remain separate from household-database backups.

Sources and rights:
- https://download.geofabrik.de/north-america/us.html
- https://www.openstreetmap.org/copyright
