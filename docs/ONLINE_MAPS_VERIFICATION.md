# Online map and route preparation verification

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
