# Hosted portal preview

The owner preview is live at **[FieldForge portal](https://fieldforge-portal.chris1986ryan.chatgpt.site)**.
It is private to the site owner. It was published successfully on October 5, 2026.

This is a static portal preview, not a public launch of the Python chat server.
The portal preserves the current map, route, library, tier and resource layout.
It adds a searchable U.S. source-region list and a Commons gallery with actual
local-test screenshots of rooms, private inbox, accounts, owner announcements
and saved-message search. The screenshots use test participants.

## What is and is not live

External provider links and the device-only skill-label preview work here.
The connection confirmation enables external source links; it does not disable
the device's internet or turn the website into an offline application.

Chat, sign-in, account/profile storage, owner authentication, geocoding, routing,
map hosting, knowledge-package hosting and billing are **not** connected to this
website. The local application remains separate. No account database,
credentials or third-party map collection was uploaded. No E2EE or screenshot
prevention is claimed. Provider descriptions are inherited from the portal;
this publication does not re-verify prices, licensing or external availability.

## Rebuild without forking the application

The original application portal is unchanged. Export it from a FieldForge
checkout with:

```sh
python tools/build_hosted_preview.py --output /tmp/fieldforge-preview --revision 6ba72816678b9271f190b34d818faa4e89d0eed7
node --check /tmp/fieldforge-preview/preview.js
```

Use the actual source commit when refreshing. The exporter deliberately fails
when expected HTML anchors change. Review and update its transformations; do
not silently publish the application API script on static hosting.

Required input: `fieldforge/online/portal.html` and the five screenshots named
in the exporter under `docs/images/`. The output contains only static HTML,
CSS, JavaScript and those images. The normal Python server is not exposed.

## Maintain this same Site

- Project: `appgprj_6ac3e4ba2c148191951eb50825d1dab4`.
- Initial Site source commit: `c6a9d1a687845d18649ccbebb262636af2b29c08`.
- Portal source snapshot: `6ba72816678b9271f190b34d818faa4e89d0eed7`.
- Site manifest: `static.directory = dist`.

Open the existing Site, refresh its source snapshot and export, then publish an
updated version with the same project identity and audience. Do not register a
replacement Site. Its own source repository retains the deployment source and
manifest; this GitHub repository retains the repeatable exporter and handoff.

Validation performed for this publication: exporter success, JavaScript syntax,
all local page/image links and fragment targets, unique element IDs, absence of
application API handlers, image inspection, and successful hosted deployment.
Live provider calls and multi-user messaging were not tested on this static Site.

## Preparation desk update — October 5, 2026

The portal now opens on two working, browser-local tools:

- **Plan map downloads:** select among 53 U.S. PBF source regions, search or show
  selected regions, compare estimated size to a decimal-GB budget, and estimate
  transfer time from an entered Mbps speed. Save/reopen a source-plan JSON file,
  or explicitly opt into device storage. A source plan is not a desktop map
  download manifest and contains no map bytes. Provider size estimates are the
  original October 4 snapshot; preparation requires extra disk space.
- **Inspect a GPX file:** choose or drop a file, draw its coordinate trace, count
  segments/points/waypoints, measure segment-aware great-circle length, and
  export explicit waypoints using the desktop place CSV columns. Files never
  upload and their coordinates are never put in browser storage. Limits: 2 MiB,
  25,000 total points and 1,000 waypoints. The preview table shows the first 100;
  CSV exports every waypoint, rounded to seven decimal places. Track geometry
  is not a basemap, driving route or route-safety assessment.

`tools/portal_preview/` contains the desk HTML, CSS, ES modules and regression
checks. The exporter now needs this sibling directory. To verify the logic:

```sh
node --test tools/portal_preview/desk-core.test.mjs
```

Ten focused checks passed for estimates, plan validation, coordinate limits,
segment boundaries, date-line crossings, polar/single-point plots, safe CSV
output, XML entity rejection, namespace traversal and point limits. XML traversal
checks use injected DOM fixtures; they do not claim browser rendering coverage.
The export was also checked for JavaScript syntax, valid local links/anchors,
matching control IDs, all 53 source regions and absence of network calls in the
preparation modules. No additional live chat or sign-in was enabled by this update.

## Route exploration update — October 5, 2026

The GPX inspector now supports bounded 1–8× zoom and pan, point selection from
the coordinate plot, a keyboard-operable point slider and previous/next buttons.
An all-waypoint picker reaches every waypoint even when the table is limited to
its first 100 rows. A selected point can be exported as the existing FieldForge
place CSV format. Metric/imperial display changes do not change coordinates.

Optional GPX elevation is read from the file only. A linked profile shows recorded
heights against cumulative segment-aware distance. Missing, malformed or duplicate
elevation records remain missing; no provider fills them in. Separate track
segments and missing-height runs are never joined. Raw ascent/descent sum only
adjacent valid heights within the same segment and are not corrected for GPS
noise. A lone valid height is plotted but cannot supply an ascent/descent estimate.
No terrain safety, driving route or reliable vertical accuracy is asserted.

Selecting a profile point updates the coordinate marker and readout. Repeated
route distances are resolved by the clicked chart position when possible; the
slider remains available for every route point. The chart labels use HTML text
to stay readable at narrow widths. Clearing or replacing a file removes the
profile, selected coordinates, waypoint options, geometry and export state.
No GPX coordinates or elevations are persisted or uploaded.

The focused Node suite now passes **17 checks**. New coverage includes genuine
zero elevation, malformed and missing heights, segment/gap boundaries, flat and
stationary profiles, repeated distances, chart point selection and bounded zoom.
Module syntax, imports, HTML control IDs and local links/anchors were also checked.
These are calculation and structure checks, not a claim of browser visual QA.
Live chat, sign-in and hosted route/map providers remain unchanged and unavailable
on this private preview.


## Local map-image viewer — October 5, 2026

The hosted preparation desk now has a third tool, **Open a map image**:

- PNG, JPEG and still WebP images are read and decoded in the browser. Files
  are limited to 32 MiB, 24 megapixels and 32,768 pixels per side. Signature,
  dimension and container checks run before native image decoding; animated
  PNG/WebP files are rejected. No files or coordinates are uploaded.
- Fit, bounded 1–16× zoom, directional pan, click selection and keyboard pixel
  selection work without geographic calibration.
- Optional full-image, north-up bounds support a latitude/longitude grid
  (EPSG:4326) or Web Mercator (EPSG:3857), including date-line crossing. Bounds
  must cover the full displayed, browser-oriented image. Pixel-center WGS 84
  coordinates can be exported as a place-catalog CSV with image provenance.
- Editing the bounds immediately disables coordinate calculations until Apply
  bounds. Bounds are user supplied, not independently verified. Borders,
  legends, rotated maps and other projections invalidate this simple method.
- A separate image-bounds JSON file can be explicitly saved and reopened. SHA-256
  of the original image bytes and the displayed dimensions must match; a
  mismatched file is rejected without replacing existing valid bounds.
- Images and bounds remain in tab memory only. Closing/clearing discards them;
  stale reads and decodes cannot repopulate cleared state. Decoded bitmaps are
  closed and image reads/decodes serialized to limit memory allocation.

This tool does not read TIFF/GeoTIFF, SVG, PDF, GIF, BMP or MBTiles, extract
georeferencing/GPS tags, fetch a basemap, or supply routing. No map dataset was
acquired or bundled. Canvas and ImageBitmap support are required; saved bounds
also require secure SHA-256 support. The page is not installed/cached for later
offline reopening. Live chat, sign-in and application hosting remain separate
unfinished deployment work.

Validation: `node --test tools/portal_preview/*.test.mjs` passes **29 tests**.
New coverage exercises format metadata, limits, date-line and Mercator transforms,
screen/pixel transforms, calibration identity, CSV provenance, and UI clear,
reopen and superseded async reads with DOM/decoder doubles. Generated HTML
labels/IDs/links, module syntax/imports and local assets were checked. Native
browser decoding and visual/device QA have **not** been run for this addition.

Technical references: [PNG header](https://www.w3.org/TR/png-3/#11IHDR),
[WebP container](https://developers.google.com/speed/webp/docs/riff_container),
[WebP lossless dimensions](https://developers.google.com/speed/webp/docs/webp_lossless_bitstream_specification),
[ImageBitmap orientation](https://developer.mozilla.org/en-US/docs/Web/API/Window/createImageBitmap),
[Web Mercator transform](https://proj.org/en/stable/operations/projections/webmerc.html).
