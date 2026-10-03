# USA map rollout — wave three

USA remains the first geographic priority; worldwide coverage remains phase two (issue #9).

## Actual prepared data

All four original Geofabrik/OpenStreetMap PBFs report **2026-10-02T20:21:34Z**. Their original bytes are preserved with ODbL attribution and acquisition receipts. A snapshot is not a check of current road conditions, and source-object counts do not imply unique addresses or complete geography.

| Region | Indexed objects | Address-tagged objects | Prepared ZIP bytes | Expanded bytes |
|---|---:|---:|---:|---:|
| Vermont | 674,627 | 338,462 | 193,748,248 | 523,180,958 |
| New Hampshire | 876,879 | 109,097 | 286,583,442 | 651,943,287 |
| Maine | 1,290,275 | 640,896 | 384,745,468 | 1,057,190,880 |
| Puerto Rico | 1,816,442 | 104,403 | 396,786,882 | 981,670,343 |

Total: **4,658,223 new indexed source objects**, including **1,192,858 address-tagged objects**. These four ZIPs are prepared map/search data, not new desktop executables. They are not automatically installed on the user's computer.

Every final linked ZIP was freshly extracted and checked using the FieldForge region verifier, CRC, source/index/rights hashes and SQLite quick_check. Actual name queries (Burlington, Concord, Portland, San Juan) and literal source-recorded house-number/street lookups passed with network sockets forbidden. Completed-job reuse passed with both networking and rebuilding forbidden. Original source files and a private sentinel were preserved.

## Road readiness

All four optional graph builds stopped explicitly:
- Vermont: unsupported restriction members, relation 2663854.
- New Hampshire: via-way/unsupported restriction, relation 1672706.
- Maine: ambiguous restriction junction, relation 3821403.
- Puerto Rico: unsupported restriction members, relation 6258000.

No restriction was intentionally discarded to obtain a path. These packs are **viewable/searchable, not driving directions**. No ETA, live closure, physical GPS, cross-state or validated navigation test is claimed.

## New code actually committed

`tools/usa_maps/acquire.py` implements bounded, explicit public-source acquisition, SHA-256 receipts, publisher-MD5 checks, fixed same-region dated redirects, failure cleanup and verified saved-snapshot reuse. `tools/usa_maps/prepare.py` adds checked preparation/export and verified reuse of completed jobs. Partial-byte download resume is not implemented. Corrupt/incomplete prior outputs are refused, never silently replaced.

The initial acquisition run refused valid provider dated redirects. Regression tests and a same-region/file-kind redirect check corrected that behavior. The successful four-region acquisition run is:
https://github.com/clryan86/FieldForge/actions/runs/37089995255

Source-tool checks and the exact small developer source archive:
https://github.com/clryan86/FieldForge/actions/runs/37090837092
Source and README commit: `a22c193301bde84782a7076aaba47c409b1d9b7d`.

**57 focused tests passed locally**, including 18 actual integration cases against the separately supplied regional backend. The 39 source-acquisition cases also passed in dedicated Linux Python 3.10/3.12 jobs. All published Python files match the tested source. Existing application files were not modified: 96 regional-backend modules remained byte-for-byte unchanged.

An actual Linux/Tk regional-map window opened Vermont data from the final ZIP, searched and selected Church Street source feature `way/18848294`, centered/zoomed and closed without Tk callback errors, with Python network calls forbidden. The screenshot is the existing regional viewer, not a new interface design or the latest Windows app.

## Dependency / repository boundary

These tools require the regional-installer backend from the chat-delivered source checkpoints for the preparation stage. This branch and GitHub main do not yet contain that complete recent desktop tree. The new tool README explicitly documents the dependency; tests requiring it skip when absent. Those tests were executed, not skipped, in the local 57-test run.

The latest full wave-two desktop ZIP was unavailable in this active runtime. A backend was reconstructed from the intact, CRC-checked regional-installer source archive plus the USA-first patch. Its 96 modules matched independently recovered CRC-checked entries. No incomplete archive is offered as a replacement desktop. The prior USVI prepared ZIP verified under this backend, and new packs use the same region-install-v1 fixed-member format. The latest desktop Import prepared pack control was not re-executed here.

Use the previous map-manager build's Import prepared pack control and select a regional ZIP without extracting it first. New data ZIPs and the small developer tools archive are delivered separately. No main merge, full-application regression, Ruff, native Windows, phone, browser or hardware GPS pass is claimed by this milestone.

## Remaining geographic work

Prepared detailed deliveries now cover **seven states**: DE, NJ, RI, HI, VT, NH and ME; plus DC, Puerto Rico and USVI. The other **43 states**, other territories, minor outlying islands and complete topographic/hydrographic/nautical collections remain outstanding. Earlier regional deliveries were not revalidated in this pass. National outlines/highways do not count as all streets. Worldwide coverage remains required after USA-first work.

## Prepared pack SHA-256

```text
513e4b1d6e51a34dfac957c7019ba30f27dbcac1e37a7b5761c5b3b54e9a4713  FieldForge-USA-Vermont-2026-10-02.zip
4f1cfe670a7302fea40c8a39032a471ba1c35e8de3198f35735d001726eb9e6d  FieldForge-USA-New-Hampshire-2026-10-02.zip
819f18c577cfa0cb3072867213e867f903bda56725f3ce1e0948537e837318ad  FieldForge-USA-Maine-2026-10-02.zip
def7c8431e6bc9aae237239fa95826444e69f77b570ae68fe43273883af7ea3a  FieldForge-USA-Puerto-Rico-2026-10-02.zip
```

Checksums are unsigned integrity records, not publisher authentication or geographic/safety certification. Map files are outside household-database backups. Preserve them separately. GitHub data artifacts retain files for 14 days; save the delivered local packs.

Sources and rights:
https://download.geofabrik.de/north-america/us.html
https://www.openstreetmap.org/copyright
