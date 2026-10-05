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
