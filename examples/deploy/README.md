# Portal deployment starter

These examples help an operator put the existing portal behind HTTPS on a
Linux host. They do not create a hostname, acquire maps or provider services,
configure billing, or make the portal publicly available by themselves.

## Before enabling public access

1. Choose a host and a domain you control. Point its DNS records to the host and
   allow inbound ports 80 and 443 for Caddy's HTTPS certificate setup.
2. Install the FieldForge package into `/opt/fieldforge/.venv`, including the
   `maps` extra for vector-tile rendering and image validation. Create an
   unprivileged `fieldforge` account and give it read access to the app,
   configuration and published map catalog.
3. Create `/etc/fieldforge/map-portal.json` with `host` set to `127.0.0.1`,
   `port` set to `8765`, `public_origin` set to the exact HTTPS origin, and
   `catalog_root` set to a directory containing only approved public packages.
   Configure address and route providers only after verifying their service
   terms, data license, attribution and capacity.
4. Replace `maps.example.org` in `Caddyfile` with the chosen domain, install the
   file in Caddy's configuration directory, and validate it with `caddy
   validate`. Install `fieldforge-map-portal.service` as a systemd unit, review
   its paths and service account, then enable the service and Caddy.
5. Test the portal over HTTPS, browser connect/disconnect, address search,
   routing, map range downloads, interrupted downloads and offline reopening.
   Monitor disk space, bandwidth, provider limits, backups and host security.

Caddy's standard reverse proxy passes request headers through by default; this
example explicitly preserves the public `Host` value because the application
checks it against `public_origin`. The standard domain configuration also uses
Caddy's automatic HTTPS. See the [Caddy reverse proxy documentation](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)
and [HTTPS quick start](https://caddyserver.com/docs/quick-starts/https).

The present portal has no user accounts, payment processor, entitlement checks
or metered-download enforcement. Treat catalog files as publicly downloadable;
do not put paid-only files behind this deployment until server-side access and
billing controls are implemented and tested. The included example config has
no map catalog or search/routing providers, so it is not launch data.
