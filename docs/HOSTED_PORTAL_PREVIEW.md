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
