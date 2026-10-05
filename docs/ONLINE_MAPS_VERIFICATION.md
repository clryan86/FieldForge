# Online map and route preparation verification

## Crowded regional map display — 2026-10-05

The real historical South Dakota index exposed a display-order defect: at the
same Sioux Falls center, zoom levels 10, 12, 14 and 16 returned 700 point features
and **zero highway lines**. Tagged nodes precede ways in the prepared source,
so a single source-ordered viewport page could exclude all roads.

Viewport selection now reserves slots for highway lines, other lines/areas,
and points. With sufficient candidates, the feature share is 2:1:1; sparse
groups give unused capacity to the others. Both longitude boxes of a wrapped
view share the limit, with deduplication before budgeting. Candidate queries
use the spatial index and read IDs/sizes first; only selected geometry is
decoded. The 700-feature viewport and 50,000-coordinate bounds remain in place,
and a feature is never cut during query selection. An oversized candidate is
skipped whole while smaller candidates can still fit. Omitted candidates keep
the view marked limited.

Exact stored bounds also refine the outward-rounded RTree boxes. In the zoom-18
comparison this excludes three nearby features outside the view: 247 features
remain, without truncation, instead of the earlier 250. It does not remove
anything from the saved map. Text-search ordering, the 100-result default,
source receipts, file fingerprint/sidecar checks, and the v1 schema are retained.
Existing saved indexes need no migration or new download.

### Installed-package and actual native acceptance

All **161 packaged source/assets** matched the reviewed checkout, wheel and
fresh installation. The real index then ran outside the checkout under
`python -S`, with neither pytest nor Pillow loaded. Inspection and searches
for Sioux Falls, Rapid City and the explicit-address query
`37756 132nd street` succeeded with Python network connections and DNS APIs
blocked. Repeated viewport requests returned identical feature sets.

The direct query comparison used latitude **43.5476008**, longitude
**−96.7293629**, and an **897 × 692** pixel viewport:

| Zoom | Earlier highway lines | Updated highway lines | Other lines/areas | Points | Total | Query time |
|---|---:|---:|---:|---:|---:|---:|
| 10 | 0 | 350 | 175 | 175 | 700 | 0.291 s |
| 12 | 0 | 350 | 175 | 175 | 700 | 0.242 s |
| 14 | 0 | 350 | 175 | 175 | 700 | 0.058 s |
| 16 | 0 | 350 | 175 | 175 | 700 | 0.016 s |
| 18 | 118 | 117 | 56 | 74 | 247 | 0.005 s |

The installed native viewer also opened the real index, searched for Sioux
Falls, selected and centered its source city point, and rendered both zooms 16
and 18. At zoom 16 it actually drew **350 highway features** and **81 text
labels**, including the selected city label, with **zero intersecting text
bounding boxes**. The complete redraw took **0.311 seconds**. At zoom 18 it drew
117 highway features and 38 nonoverlapping labels in 0.259 seconds. The window
controls and attribution remained visible, coordinate copy matched the source
point, no Python network/DNS call was attempted, no Tk callback failed, and
worker threads stopped on close.

- [Actual crowded view at zoom 16](screenshots/south-dakota-crowded-map-z16.png)
- [Actual detailed view at zoom 18](screenshots/south-dakota-crowded-map-z18.png)
- [Installed offline query record](verification/south-dakota-crowded-map.json)
- [Installed native rendering record](verification/south-dakota-crowded-map-native.json)

The map was **384,290,816 bytes** before and after both checks, with unchanged
SHA-256 `1f34bd020350eb72f2ec6cf24059cd15c6b80c0184988eb5209f89c81df8a91a`.
It contains the previously verified 626,562 features from the source snapshot
of 2026-10-02T20:21:34Z. These are Linux measurements using Tk 9.0.4 and a
temporary authenticated loopback display. They do not establish other-device
performance, complete geographical coverage or usable routing.

### Rendering limits and regression coverage

The regional and small-PBF viewers now allocate ordinary drawing capacity to
roads first, then restore visual layers with points/area outlines below roads.
Text placement measures actual Tk bounding boxes, reserves caption space and
places the selected feature's label before ordinary names. Long geometry is
projected in bounded chunks with shared source endpoints; no nonadjacent nodes
are joined. Clipped geometry supplies the label anchor when a source midpoint
is outside the screen.

The selected overlay has its own allowance of 5,000 original segments. Ordinary
geometry remains bounded at 20,000 segments and 1,500 point markers; at most 500
ordinary label candidates and 80 accepted ordinary labels are processed. A
long selected feature that exceeds its allowance is visibly labeled and
explicitly reported as partly drawn. **VIEW LIMITED** and **DRAW LIMITED** are
kept distinct. A tiny canvas shortens only the selected annotation; the full
source name stays in the details.

The update adds **26 regional-query cases and 12 native Tk rendering cases**.
Coverage includes dense points/buildings before roads, sparse-group refill,
small/maximum limits, malformed geometry, complete-path query budgets, exact
bounds, date-line deduplication, cancellation, real glyph overlap, selected
geometry under exhausted ordinary budgets, clipped gaps, tiny canvases and
truthful limit messages. These tests are included in both native Linux and
Windows map workflows. Independent review found no blocker and confirmed
in-flight statewide-query cancellation and chunked date-line equivalence.

Final local regression verification passed **818 tests and 78 subtests**, with
no skips, in 40.87 seconds. This is the native map-workflow set plus the 92
source/projection cases; focused reruns are not counted again. Repository-wide
Ruff, patch whitespace, Python 3.10 grammar parsing, and native workflow test-path
checks passed. The temporary test runner destroys its display-startup probe
before pytest creates fixture roots, keeping native widgets and their Tk
variables in the same interpreter. The real-map acceptance intentionally uses
the single root supplied by that display helper. Hosted Windows/Linux/browser
results are recorded on the development PR for the saved commit.

This update improves an existing source map's display and search workflow.
Offline route calculation, broader verified U.S. payloads and public hosting
remain separate unfinished work.


## Historical package compatibility and Windows map publication — 2026-10-05

The exact original South Dakota prepared ZIP was recovered locally and checked
against its historical collection. It exposed a real compatibility failure:
its collection retained `south-dakota-latest.osm.pbf`, while the unchanged index
receipt used the installer's internal `source.osm.pbf` name. Collection conversion
now accepts that historical alias only through one bounded, adjacent
`region.json` that binds the original name and region to the measured map hash,
source fingerprint, snapshot, feature counts and license. Other filename
mismatches still fail. The map bytes and embedded metadata remain unchanged;
the preparation receipt retains both names and the wrapper fingerprint, and
the catalog displays the checked original name.

Both PBF preparation and regional ZIP import now use non-overwriting rename on
Windows, retaining hard-link publication on POSIX. This removes their dependence
on Windows hard-link support while preserving existing or competing files and
cleaning up private staging files. Local platform fixtures exercise the Windows
branch; hosted Windows tests supply actual Windows execution. No particular
removable drive was available for hardware testing.

### Exact historical package acceptance

A fresh installed wheel ran the documented `python -S -m
fieldforge.online.catalog prepare-collection` and `build` commands in separate
processes outside the checkout. The test selected only South Dakota from the
four-record collection; the other ZIPs were absent. It published the resulting
inventory, served and downloaded the map over real loopback HTTP using a saved
download list, then retried with any second file download forbidden. The retry
verified and reused the completed map.

After the test's archive copy, collection, prepared inventory and published
catalog were removed and the server stopped, the saved map reopened and
searched successfully with socket connections blocked. Sioux Falls and Rapid
City each returned the bounded first 100 matches, with the limit flag set;
these are not total city-result counts. No network connection was attempted.
The original saved package was preserved throughout.

| Verified item | Result |
|---|---|
| Original package | `FieldForge-USA-South-Dakota-2026-10-02.zip`, **194,212,607 bytes** |
| Unchanged prepared index | **384,290,816 bytes** |
| Source snapshot | **2026-10-02T20:21:34Z** |
| Indexed features | **626,562** |
| Address-tagged source objects | **17,522** |
| Missing-node ways | **0** |
| Installed CLI collection preparation | **6.159 seconds** |
| Installed CLI catalog publication | **4.800 seconds** |
| Verified HTTP download list | **4.764 seconds** |
| Verified local retry without a second file transfer | **0.251 seconds** |
| Offline reopen, integrity and city searches | **4.702 seconds** |

The original archive SHA-256 is
`66c2a7ed66ab3c37a770db097038513670254e6f73878142cb0503288c3f324e`;
the unchanged historical index SHA-256 is
`1f34bd020350eb72f2ec6cf24059cd15c6b80c0184988eb5209f89c81df8a91a`.
These identify the historical package and index, separately from the later
source-derived package documented below. Both indexes reference source PBF
SHA-256 `43ee4e5a620dc050735a6ab224cda5dc049e83f42bded062e1539e389a81d643`.
The conversion checks source declarations; the independent recovery check also
hashed the actual original PBF and matched the source receipt.

[Machine-readable acceptance record](verification/south-dakota-historical-collection.json)
contains the measured fingerprints, unchanged source receipt, wrapper binding,
result samples, stage timings and loaded-code hashes. Performance figures are
measurements from this Linux environment. The bounds include neighboring
geography and do not establish complete coverage or validated navigation.

### Regression and native verification

- **601 backend/map tests and 78 subtests passed**, with no skips, after all
  production changes were frozen.
- **28 actual Tk regional-portal UI cases passed**, requiring a working display.
- The change adds **54 wrapper-receipt cases**, **28 regional publication cases**
  and **one successful independent CLI chain**. The existing source-name mismatch,
  input-change, no-clobber and cancellation cases remain.
- All **161 packaged source/asset files** match the checkout and freshly
  installed wheel. The real-data CLI acceptance used `python -S`, with pytest
  and Pillow unavailable; all 20 loaded FieldForge modules matched the installed
  and reviewed source bytes.
- Repository-wide Ruff, patch whitespace, workflow YAML and referenced test
  paths passed. Both map-platform CI jobs include the new modules.

The first hosted map run for `dcfa938` passed **688 Linux/Tk tests and 78
subtests**, plus **11 Chromium scenarios**. Its Windows job reported **685
passed, one failed, two skipped and 78 subtests**. The failure was in the new
malformed-backslash ZIP fixture: Windows `ZipInfo` normalized the requested
backslash into a valid forward-slash path while creating the test archive.
The test was therefore passing a valid adjacent receipt to the importer.
The fixture now explicitly writes its intended filename and checks the raw
`orig_filename` from the resulting archive before exercising the rejection.
The rejection assertion and production validation remain intact. The two
Windows skips are the existing POSIX named-pipe and symlink-privilege cases.
The corrected fixture passed all **107 collection/receipt cases** locally,
and all eight unsafe/adjacent path cases also passed with isolated Windows
filename-normalization behavior. Hosted results for the corrective commit
remain tracked by the map compatibility workflow.

The [actual native offline view](screenshots/south-dakota-offline-map.png) shows
Sioux Falls streets and buildings from the historical index. The window opened
the real file, searched for Sioux Falls, centered its source city point and
copied its recorded coordinates with network connections blocked. This is an
application screenshot, not generated cartography. The capture used a temporary
Tk 9.0.4 runtime with registered DejaVu fonts; production UI code was unchanged.
At zoom 18 the view contains 250 features, including 118 highway line features,
without reaching the viewport cap. At zoom 16 the existing 700-feature cap
returned point features before road lines. That defect is fixed by the crowded-view update documented above. Search
results remain bounded at 100 as labeled in the UI.

The data remains a bounded source display/search index; it adds no offline
routing graph, public map hosting, complete-U.S. coverage or verified
installation on the user's device.

## Regional collection preparation — 2026-10-05

`fieldforge-map-catalog prepare-collection` connects a saved
`fieldforge-map-collection-v1` record and explicitly selected local ZIPs to the
ordinary inventory publisher. The command verifies selected archive bytes,
imports only each `map.ffmap`, compares the inspected source/count/license
receipt, and derives numeric coverage and source-based versions. A preparation
receipt distinguishes measured ZIP/map checksums from the original PBF identity
declared by the collection and embedded index. No unselected archive, route
graph or device installation is processed.

The **53 new focused tests passed**. They use real synthetic PBF/index/ZIP
fixtures and cover selected-only access, absent unselected packages, malformed
documents and archive entries, source changes, metadata mismatches, interrupted
multi-map work, and preservation of existing/concurrent destinations. A complete
test builds the ordinary inventory, serves it over local HTTP, downloads through
the desktop client, removes the source inputs and catalog, then searches the
saved index with network connections blocked.

Review caught and corrected directory spelling differences (`..` and Windows
short names), a preparation/publisher title-limit mismatch, and exception-class
differences under actual `python -m` execution. The cases verify a 240-character
title prepares and publishes, a 241-character title produces no ready output,
and both preparation/build CLI errors exit with readable messages and no
traceback. Validated inventory publication is the commit point; a later private
staging cleanup error can leave the complete output, as documented in the API
and operator guide.

A fresh wheel was installed outside the checkout. All **161 packaged source
and asset files** match both the reviewed source and installed bytes. The new
command loads under `python -S` outside the checkout. Repository-wide Ruff,
patch whitespace, workflow YAML and referenced test paths pass. Both Linux and
Windows map jobs now run the collection module alongside the existing regional,
portal and native workflows. The 53-case result is local Linux validation;
hosted results for the collection commit are recorded by Actions.

The original South Dakota source was also recovered through a separate
[verified artifact recovery job](https://github.com/clryan86/FieldForge/actions/runs/37322179144).
The reconstructed acquisition ZIP is 49,423,079 bytes with SHA-256
`83dbf47ee61a2daecd4d5d7e94ae20d47508df95c843fa09bfc4d93e16c979de`.
Its actual PBF is 49,414,046 bytes with SHA-256
`43ee4e5a620dc050735a6ab224cda5dc049e83f42bded062e1539e389a81d643`,
matching the original source receipt and collection record. The source receipt
names the 2026-10-02 Geofabrik snapshot. This recovery is of the original
source, not the previously prepared 194 MB package; a new preparation has its
own receipt and finished-map checksum.

### Actual South Dakota acceptance

The full source-to-offline-download workflow passed using that fresh installed
wheel, outside the checkout with `python -S`. Pillow and pytest were unavailable
and unimported. All loaded FieldForge modules came from the installed package,
and their recorded source hashes remained unchanged during the run.

| Measured item | Result |
|---|---|
| Source snapshot | **2026-10-02T20:21:34Z** |
| New prepared map | **384,290,816 bytes** |
| Indexed features | **626,562** |
| Features with explicit house-number and street/place tags | **17,522** |
| Ways with missing source nodes | **0** |
| Indexed extent, west/south/east/north | **−105.5310248, 40.3387377, −95.0817848, 47.3719077** |
| Prepare source PBF | **101.812 seconds** |
| Inspect the finished map | **4.123 seconds**, using the unchanged 30-second limit |
| Convert the selected package into an inventory | **5.731 seconds** |
| Publish the ordinary inventory | **4.517 seconds** |
| Verified download over real local HTTP | **4.859 seconds** |
| Inspect the downloaded map while offline | **4.179 seconds** |

The finished map's SHA-256 is
`9e5a05c53702bf33095b599845b5693d49028afec8a30c25833b2b8a1d835e8c`.
Its embedded source identity and feature/address/missing-node counts agree with
the historical collection. The source contains 7,160,778 nodes, 575,053 ways,
7,975 relations and 675 turn restrictions. The prepared display index counts
those restrictions but does not apply them as a routing graph.

After the server was stopped and socket connections were blocked, the saved
download produced exactly the same search results as the prepared source index.
Both **Sioux Falls** and **Rapid City** returned the bounded first 100 matches
with the limit flag set; these are not total city-result counts. The explicit
address query **37756 132nd street** returned **SEAL Livestock**,
`node/78770266`, from its actual address tags. The three offline searches took
0.008, 0.005 and 0.003 seconds respectively. No network connection was attempted.

These are measurements in this Linux test environment, not performance promises
for another device. All preparation, inspection and interactive-query limits
were unchanged. The measured extent crosses state borders and does not certify
complete coverage inside its rectangle. The package is a new display/search
derivation from the October 2 source; it adds no routing graph, public hosting,
verified user-device installation or claim of four-state/U.S. completeness.

## Windows portability follow-up — 2026-10-05

The first hosted run for `a43e25d` passed Linux Tk and Chromium but exposed
Windows failures in the regional source opener and three test fixtures. The
[map compatibility run](https://github.com/clryan86/FieldForge/actions/runs/37317039859)
recorded 17 failed tests and 8 setup errors on Windows; its Linux job passed.
The separate [Commons run](https://github.com/clryan86/FieldForge/actions/runs/37317040022)
passed for the same commit.

The source opener now compares device, inode, size and modification time
between the pathname and file handle, then checks the complete pathname
signature, including change time, before and after opening. This follows the
existing download-storage approach: Windows can report different change times
through the two APIs. Complete pathname checks after PBF reading and archive
extraction remain in place. Regular-file checks and descriptor cleanup are
unchanged.

The fixture corrections resolve both destination paths before comparing them,
explicitly close two SQLite connections after committing, and inject a route
publication failure at the shared publication helper used on both platforms.
They retain the original destination, cleanup and failure assertions.

Focused local verification passed **195 tests and 78 subtests**, with no skips:
124 regional-reader, identity and portal tests, plus 71 server/storage tests.
The 17 new identity cases cover actual replacement with preserved size/mtime,
changes during opening and reading, handle-only change-time differences,
descriptor cleanup on interruption, and real PBF preparation/archive import.
Independent review found no blocking issue. Both draft-branch platform jobs
and the main workflow now include this module.

Corrective commit `6db7f54` passed its
[hosted map workflow](https://github.com/clryan86/FieldForge/actions/runs/37319834164):
**550 Windows tests and 78 subtests**, with two platform-specific skips;
**552 Linux Tk tests and 78 subtests**, with no skips; and **11 Chromium
scenarios**. The Windows skips are the existing POSIX named-pipe case and a
symlink-creation case requiring extra Windows privileges. All regional identity
and native viewer cases ran. The
[Commons workflow](https://github.com/clryan86/FieldForge/actions/runs/37319834112)
also passed for this corrective commit.

## Prepared regional portal workflow — 2026-10-05

Prepared `.ffmap` indexes now use the shared immutable publisher, catalog,
canonical and compatibility download clients, and saved download lists. They
retain a distinct `regional` family, a 4 GiB limit, their finished-file SHA-256,
and their unchanged embedded source receipt. Both publication and installation
validate a nonempty, closed SQLite index with the existing regional inspector.
This increment uses local fixtures; it does not acquire or host the previously
shared state packages or claim complete U.S. coverage.

The browser and native catalog filters identify prepared regional maps, and all
three desktop handoffs open the regional viewer. Actual Tk execution exposed an
existing constructor defect: a copy button was gridded inside ScrolledText's
packed internal frame. Using the established outer controls pane fixes opening
the viewer. The native checks now open and search the completed index after
removing its source PBF, and exercise busy cancellation, deferred close, forced
parent destruction, late replies, and GPS ownership without starting a receiver.

| Local check | Result |
|---|---|
| Map, portal, regional-reader, native UI, file-identity, image and route-overlay regression group, with a required working Tk display | **585 passed, 78 subtests passed**, no skips, in 64.69 seconds |
| Actual Chromium portal workflows | **11 passed**, including the regional filter, mixed browser list export, explicit desktop installation and offline search |
| New checks included in those totals | **18 backend/HTTP**, **28 native/lifecycle**, and **1 browser** case |
| Repository-wide Ruff, patch whitespace, and bundled portal JavaScript syntax | Passed |
| Main and draft-branch workflow YAML and referenced test files | Parsed successfully; all referenced test modules exist |
| Fresh installed wheel, outside the checkout with `python -S` | Published, served, downloaded and reopened a real prepared index; all **14 modified packaged source/assets** match the reviewed source bytes |

The browser round trip selects `.ffmap`, MBTiles and an image, confirms that
filtering makes no extra requests, downloads the exact regional bytes, exports
the list while offline, and installs it through a separately connected desktop
client. The installed index is then inspected and searched with socket connects
blocked. Layout assertions pass at 390 and 1280 pixels. Browser-native downloads
display the catalog checksum but do not independently perform the desktop
installer's verification.

The native/backend group covers real HTTP and compatibility downloads,
mixed-format inventory publication, exact remaining-byte range requests,
checkpoint reuse, source/provenance retention, wrong or empty SQLite indexes,
WAL/journal rejection, a source-sidecar staging race, oversize files, and
cancellation/disconnection after inspection but before installation.

The package smoke prepared the committed 9,653-byte historical PBF into an
81,920-byte index with 51 features, then used the installed publisher, HTTP
server and client. After deleting the inputs and published origin and blocking
socket connects, the downloaded index still returned the expected Wellfield
Road search result. Its bytes, embedded receipt and download provenance matched.
Every loaded FieldForge module came from the installed wheel; Pillow and pytest
were unavailable and unimported. This confirms regional preparation and
download/search work without those optional packages. It is not a Windows
standalone executable test or a claim of present-day map coverage.

[Browser catalog screenshot](screenshots/regional-portal-catalog.png) shows a
clearly labeled synthetic fixture and a three-map selection. It is a workflow
demonstration, not a supplied regional dataset.
[Native regional viewer capture](screenshots/regional-viewer.png) shows the
actual offline search, selected geometry and repaired pane layout. Some Unicode
symbols render incorrectly in this temporary Linux test environment; the image
records that runtime limitation and is not a Windows appearance preview.

The new **Map portal compatibility** workflow runs on this draft branch and PR
base, with required Linux Tk/Chromium and Windows Tk jobs. The ordinary main CI
also includes the new native and Chromium/WebKit modules. Hosted platform
results are reported by GitHub Actions; local Chromium/Tk results do not imply
a local Windows or WebKit run.

Reproduce the principal checks from a source checkout with `.[dev,maps]`, Tk,
Xvfb on headless Linux, and the existing pinned Playwright 1.57.0 browsers:

```bash
FIELDFORGE_REQUIRE_GUI=1 xvfb-run -a python -m pytest -o addopts='' -q -ra \
  tests/test_regional_portal.py tests/test_regional_portal_ui.py \
  tests/test_regional_index.py tests/test_online_client.py \
  tests/test_online_compat.py tests/test_online_server.py \
  tests/test_online_storage.py tests/test_online_resume.py \
  tests/test_online_portal.py tests/test_online_maps_ui.py \
  tests/test_online_compat_ui.py tests/test_online_integration.py \
  tests/test_portal_catalog.py tests/test_portal_connection.py \
  tests/test_map_download_list.py tests/test_gps_desktop.py \
  tests/test_maps_ui.py tests/test_maps_integration.py \
  tests/test_route_overlay_ui.py tests/test_image_maps_ui.py \
  tests/test_map_file_identity.py

FIELDFORGE_PORTAL_BROWSER_TESTS=1 python -m pytest -o addopts='' -q \
  tests/test_online_portal_browser.py tests/test_regional_portal_browser.py
```

## Earlier integration checkpoints

The remaining sections preserve earlier verification and runtime limitations
from 2026-10-04; they do not describe the latest regional-map run above.

Local verification date: **2026-10-04 (UTC)**. This integration reconciles the
public portal work through `3102d0d5c1234ce647f7157dabde417cc0642ac3` with the
optional Online Maps tab, shared hosting/client implementation, saved route
files, and offline route overlay. The earlier clean baseline used for the Tk
control described below was `68e5011d7b6cec4552e82b8985b449dac78b182f`.
See [Online map portal](ONLINE_MAP_PORTAL.md) for operation and supported formats.

## Coordinate-based map discovery

The native map tab and browser portal now filter the loaded catalog by an
explicit latitude/longitude pair. Selected address results can fill these
filters without a request; existing download-list selections remain intact.
Text-only coverage is excluded and counted rather than guessed. Compatibility
catalogs keep their text filters because their coverage field is a label.

The 35 new headless cases cover inclusive boundaries, date-line crossings,
equivalent +180/-180 longitudes, zero-width extents, poles, labeled or malformed
coverage, explicit coordinate validation and blank/half-filled form semantics.
Required GUI checks exercise address handoff with and without a loaded catalog,
offline filtering, retained selections and minimum-window visibility. A real
browser workflow covers the same filtering and date-line boundaries, invalid
inputs, offline address reuse, list retention and a 390-pixel mobile layout.

Local Python 3.12.14 headless validation: **2,247 passed**, 535 GUI/browser skips,
78 subtests passed and two existing PDF-fixture deprecation warnings. Ruff,
whitespace and portal JavaScript syntax checks pass. The PR records the exact
revision's Linux desktop, Windows, Chromium/WebKit and packaging results;
headless skips are not counted as graphical validation.

## Resumable partial map transfers

The native list window now keeps partial downloads for explicit retry, with a
visible checkbox and confirmed offline discard action. Native HTTP and WSGI
serve bounded single byte ranges with strong SHA-256 ETags. Checkpoints bind
the exact portal, asset and destination filename, verify the stored prefix, and
use OS locks so parallel transfers cannot write one checkpoint. No automatic
reconnection or background transfer was added.

The 48 new transfer regressions cover both real portal hosts, exact remaining
network byte counts after a fresh-client retry, short responses, invalid range
metadata, fallback to full responses, corrupt or mismatched local checkpoints,
durable checkpoint intervals, uncommitted crash tails, process-exit lock release,
hard-link protection, full-file verification and cancellation during publication.
The latter restores the complete checkpoint on Windows for retry without
transferring map bytes again.
Desktop checks cover opting out, confirmed offline discard while preserving
completed maps, minimum-window controls and owned Tk-variable cleanup.

Local Python 3.12.14 headless validation: **2,212 passed**, 532 GUI/browser skips,
78 subtests passed and two existing PDF-fixture deprecation warnings. Ruff and
whitespace checks pass. The built wheel installs away from the source tree and
includes checkpoint storage, range serving and the updated desktop window.
The PR records the required Linux desktop, both Windows versions,
Chromium/WebKit, frozen Windows delivery and source-bundle checks. No local
graphical run is inferred from headless skips.

## Map download lists and verified batch transfers

The next extension adds portable map selections to the browser and native
desktop. Selections show total file bytes and survive filtering/disconnection;
JSON export/import is local. The desktop explicitly connects to the list's
portal, checks the current catalog and downloads sequentially. Completed maps
are retained on interruption and verified locally before reuse on a retry.
At this earlier checkpoint, partial-file byte-range resumption remained future
work; the extension above now supplies it for native download lists.

Python 3.12.14 local headless result: **2,164 passed**, 529 GUI/browser skips,
78 subtests passed and two existing PDF-fixture deprecation warnings. Ruff and
JavaScript syntax checks pass. Real desktop and browser workflows are required
by the PR's CI jobs, including Windows publication and frozen delivery checks.

The new local HTTP tests cover saved-list round trips, origin binding, bounded
imports, duplicate IDs/names, stale catalogs, exact-byte reuse, changed local
bytes/provenance, no overwrite, stopping before the next file and cleanup during
an active transfer. GUI tests cover review/import/export, offline editing,
explicit batch start, cancellation, foreign-portal controls and Tk cleanup.
The browser test exports selections across pages/filters while offline, then
imports and downloads that exact list with a separately connected real client.

The initial hosted run caught a queued-selection event in the GUI test and a
Windows path/handle ctime precision difference in completed-map verification.
The test now processes the selection event before clicking Add. Reuse compares
identity, size and mtime across path/handle APIs, then compares each API's full
signature across the read and verifies SHA-256. Two additional regressions
accept stable cross-API ctime differences while rejecting a change during the
read. The PR links the corrected platform run and its Windows package.

## Portal home, consent, map discovery and inventory extension

The subsequent portal extension adds a default-No connection warning and
browser-home handoff, labeled knowledge-pack placeholders and draft tier notes,
local map filters/size sorting, browser pagination, and inventory publication
through the shared immutable map publisher. It preserves the platform fixes
and subsequent Tk lifecycle cleanup through `5ca680deb55e63389a076a115f8b66f3a3152a75`.

Local Python 3.12.14 headless verification for this extension: **2,142 passed**,
523 GUI/browser skips, 78 subtests passed, two existing PDF-fixture deprecation
warnings. Ruff and whitespace checks pass. These skipped graphical tests are
not claimed as executed locally. The PR's required Linux GUI, Windows map and
Chromium/WebKit jobs exercise the real interfaces and Windows delivery builds.

New regressions cover rejecting connection without a request or browser launch,
opening the browser once per explicit connection, a copyable-link fallback,
correct map identity after filtering, offline catalog discovery, paging without
requests, actual filtered image download bytes, mobile home layout, and atomic
bulk publication with invalid files, changed sources, preserved rights metadata,
no-overwrite behavior and rollback. Test inputs use synthetic maps/addresses.
The homepage's other download categories and tier allowances remain explicit
placeholders; no rights clearance, public deployment or billing is inferred.

## Earlier integration local results

The implementation was checked with Python 3.12.14. Graphical checks used a
real Tk 9.0 display under Xvfb; the browser script also ran under Node.

| Check | Result |
| --- | --- |
| Complete headless checkpoint after the map-publication/mobile-layout corrections | **2,117 passed**, 516 skipped, 78 subtests passed; 2 existing PDF-fixture deprecation warnings |
| Broad desktop, map, place, GPS, and portal integration checkpoint with a required display | **149 passed**, no skips; includes the 54 HTTP/compatibility cases also covered headlessly |
| Focused publisher and actual portal/client/desktop integration after the Windows correction | **48 passed**, 78 subtests passed, no skips |
| Final online, compatibility, place, and UI-lifetime group with a required display | **61 passed**, no skips or warnings; tracked original finalizers and weak references confirm UI-thread cleanup while closed window objects remain referenced |
| Ruff and patch whitespace | Passed |
| Wheel build | Passed; includes the portal HTML and shared image validation module |
| Installed wheel outside the source checkout, with site packages disabled | Native HTTP and the WSGI compatibility factory served the exact bundled HTML, CSP, status API, and empty configured map catalog; both client APIs connected/disconnected explicitly |
| Visual desktop inspection | Address search, map downloads, and route panels fit at 1200 × 850 without overlapping controls; the final main-tab layout regression also passes at 1000 × 700 |

The 516 headless skips are reported as skips, not executed graphical/browser
checks. The separate integration group above required a working display.

The required-display integration group was:

```bash
FIELDFORGE_REQUIRE_GUI=1 xvfb-run -a python -m pytest -o addopts='' -q \
  tests/test_online_integration.py tests/test_online_maps_ui.py \
  tests/test_online_compat_ui.py tests/test_online_portal.py \
  tests/test_route_overlay_ui.py tests/test_maps_ui.py \
  tests/test_maps_integration.py tests/test_places_ui.py \
  tests/test_places_integration.py tests/test_gps_desktop.py \
  tests/test_packaged_ui.py
```

## Exercised handoffs

The integration tests run actual local HTTP providers and the actual portal,
using synthetic maps and coordinates. They verify explicit connection, address
selection, coordinate/provenance preservation in the normal place editor,
catalog download, byte-for-byte map integrity, route alternatives, and saving.
They then disallow new network connections and reopen the local map, saved
place, route directions, and planned GPX track.

Desktop checks cover disabled online controls at startup/disconnection, worker
cancellation, late-result rejection, local file import, reopening, and cleanup.
Selected routes retain their own start/destination coordinates. Changing the
endpoint form labels the selected plan as using previous coordinates until a
matching plan is selected or opened.

Compatibility checks exercise both client APIs against the unified HTTP/WSGI
service and literal older wire responses. They preserve the original map and
route endpoints, exact chosen download filenames, source sidecars, current
place-editor prefill, GPS manual fields, and offline CSV/GPX exports. Legacy
geometry-only routes are accepted without inventing written instructions.
The original 45 portal and five desktop compatibility tests are retained
semantically, with added checks for migration errors, provenance, explicit
connection, request cancellation, endpoint tracking, and file-action cleanup.

The offline overlay uses the route's actual geometry, preserves adjacency,
handles the dateline, clips to the viewport, and avoids inventing a segment
across omitted polar points. GPX export preserves planned geometry without
fabricating receiver fixes or point timestamps.

Review regressions include OSRM HTTP 400 `NoRoute`/`NoSegment` becoming an empty
successful route result, while real/malformed upstream errors remain failures.
The publisher and downloader share image validation: a real 32-million-pixel
PNG is accepted, and a small compressed PNG containing 32.8 million pixels is
rejected before publication. Neither workflow downloads public map tiles.

The actual browser JavaScript download handler was executed with a route of
50,000 points and 10,000 instructions. Its compact 6,544,029-byte download
imported and reopened in the real desktop storage layer. The former indented
representation was 8,784,179 bytes and exceeded the 8 MiB document limit. A
complete envelope one UTF-8 byte over that limit was blocked without losing
the selected route. A separate storage regression exercises the exact
normalized-route byte boundary and same-file reimport.

## Hosted platform corrections and verification limits

The first hosted runs found three additional issues. Playwright needed a normal
Python event callback instead of a built-in list method in one download test.
Windows refused to delete a read-only temporary map name after publication;
the publisher now installs without replacement, removes the temporary name
while writable, and then marks the final object read-only. A portable regression
also verifies exact bytes, deduplication, cleanup, and a competing destination.
WebKit exposed narrow-layout overflow with long provider text; the portal now
allows the relevant grid tracks and controls to shrink and wraps endpoint hints
and directions. Both strict mobile-width assertions remain in place, with
element-size diagnostics on failure. The PR links the final hosted run so these
corrections can be checked on the actual platforms.

A passing Windows 3.12 map run also logged a Tk variable-finalizer warning. The
main Online Maps tab retained two detail-panel traces and a container of endpoint
variables. Inspection closed those retention paths; an allocation probe then
identified five remaining variables from the destroyed place editor being
finalized on a background thread during the real online-to-saved-place workflow.
Both windows now use the existing UI-thread cleanup helper. Tab close removes
all six owned traces and parent callbacks; destruction releases its widget and
variable references. Place-editor destruction also clears its owned field
dictionary and completed callback. The regressions retain plain selected data,
record/change diagnostics, and worker diagnostics while confirming that owned
Tk variables finalize on the UI thread.

A complete all-tests run with this environment's Tk 9.0 runtime aborted in
native code during garbage collection in an existing starter-library worker.
The same abort was reproduced by running `tests/test_starter_ui.py` alone in a
clean worktree of the unchanged baseline commit above. The 149-case
required-display integration group completed successfully. A complete local
all-GUI-suite pass is not claimed.

Chromium/WebKit binaries and a Windows runtime were unavailable locally. The
existing CI workflow now includes the portal browser tests, the new desktop
workflow/overlay tests in its Linux and Windows GUI jobs, and the packaged HTML
check. The browser tests require real browser downloads, an offline import/GPX
round trip, literal rendering of provider labels, mobile-width layout, and the
large UTF-8 export boundaries. The six portal browser cases also cover explicit
consent/connect, no automatic reconnect, late-response rejection, and offline
CSV/source-note export. Their hosted results are reported on the PR/CI run, not
inferred from the local Node execution.

This verification does not provision or establish public hosting, worldwide
map coverage, live provider reliability, or real-road navigation accuracy. Map
packs and provider services must be supplied by the operator. Saved routes
retain a requested plan; offline route calculation and rerouting remain outside
this implementation.
