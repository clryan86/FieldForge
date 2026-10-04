# Online map and route preparation verification

Local verification date: **2026-10-04 (UTC)**. This integration reconciles the
public portal work through `3102d0d5c1234ce647f7157dabde417cc0642ac3` with the
optional Online Maps tab, shared hosting/client implementation, saved route
files, and offline route overlay. The earlier clean baseline used for the Tk
control described below was `68e5011d7b6cec4552e82b8985b449dac78b182f`.
See [Online map portal](ONLINE_MAP_PORTAL.md) for operation and supported formats.

## Local results

The final local source was checked with Python 3.12.14. Graphical checks used a
real Tk 9.0 display under Xvfb; the browser script also ran under Node.

| Check | Result |
| --- | --- |
| Complete headless pytest suite | **2,115 passed**, 516 skipped, 78 subtests passed; 2 existing PDF-fixture deprecation warnings |
| Targeted desktop, map, place, GPS, and portal integration group with a required display | **149 passed**, no skips; includes the 54 HTTP/compatibility cases also covered headlessly |
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

## Verification limits and hosted checks

A complete all-tests run with this environment's Tk 9.0 runtime aborted in
native code during garbage collection in an existing starter-library worker.
The same abort was reproduced by running `tests/test_starter_ui.py` alone in a
clean worktree of the unchanged baseline commit above. The final 149-case
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
