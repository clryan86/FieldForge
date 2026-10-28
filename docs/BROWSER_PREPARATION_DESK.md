# Browser preparation desk

The hosted preview and downloadable offline HTML use the same local GPX and
MBTiles tools. In **Inspect a GPX file**, choose a GPX and press **View GPX on
map**. This creates a snapshot of its original coordinates. A map pack is
optional for inspecting the snapshot's points and distances.

## Segments and selected-point distances

Use **Jump to a segment or waypoints** to select the first original point of a
segment, or the first separate waypoint. Each segment entry includes its point
count and approximate length. The point slider and Previous/Next buttons update
the selector when crossing a segment boundary. Use **Centre on GPX point** to
move an open MBTiles map to the selected coordinate.

The distance readout shows the selected point's approximate distance from its
own segment's start, the distance to that segment's end, and the previous
recorded leg. It never counts a gap between separate segments or a connection
to a waypoint. An isolated point has no connected trace; two identical adjacent
points have a real zero-length leg. Longitude +180 and -180 represent the same
meridian. Date-line legs use the short great-circle arc.

These distances describe the supplied GPX geometry. They do not include
elevation, infer roads or calculate directions. The map draws straight Mercator
edges; those lines can differ from the great-circle distance model. Exactly
180-degree longitude edges remain omitted from the drawing and rejected by the
tile-path check as ambiguous, even though endpoint distance can be measured.

Changing the selected segment preserves the tile-check report. Replacing or
removing the overlay clears its navigation state. Opening a local map preserves
the current overlay point; closing the map clears the overlay. Original files
are unchanged. Save any collected places separately and reopen original GPX and
MBTiles files in the next session.

## Development verification

From the repository root, run the dependency-free export and JavaScript checks:

```sh
python -m unittest discover -s tools -p 'test_*.py'
node --test tools/portal_preview/*.test.mjs
```

Require the native browser workflow after installing Playwright and Chromium:

```sh
python -m pip install 'playwright==1.57.0'
python -m playwright install chromium
FIELDFORGE_PORTAL_BROWSER_TESTS=1 PYTHONPATH=tools python -m unittest tools/test_offline_desk_browser.py -v
```

The native test opens the generated HTML through a local file URL with browser
networking disabled. At desktop and phone widths it exercises keyboard segment
selection, distance updates, an embedded-worker MBTiles open, retained selection,
waypoints and cleanup, and checks page errors, network requests and overflow.
Set `FIELDFORGE_OFFLINE_SCREENSHOT_DIR` to retain screenshots. An existing local
browser executable can be supplied with `FIELDFORGE_BROWSER_EXECUTABLE`.

The embedded reader prefers the pinned SQL.js 1.14.2 WebAssembly build and
includes its binary in the same HTML. This avoids the first-query stack overflow
reproduced with that release's JavaScript build in Chromium 143. A separate
JavaScript build remains available when WebAssembly is disabled; both engines
have raster/vector and no-network regressions. Builds verify all three upstream
asset hashes. The offline CSP permits WebAssembly compilation while continuing
to block JavaScript string evaluation, external resources and network requests.

The map-portal workflow runs the export and JavaScript suites in its offline-desk
job and requires the native browser test in its Linux map job. Changes under
`tools/` trigger that workflow.
