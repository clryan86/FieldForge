# FieldForge global map data and purchase queue

Status checked 2026-10-04. This is an acquisition and compatibility record, not a claim that these datasets are installed, licensed to FieldForge, or available from its portal.

## What “all MBTiles” means for FieldForge

MBTiles is a container specification, not a single global map collection. It permits image tiles and vector tiles, and a file's geographic coverage, zooms, data age, content, style, and reuse rights depend on the specific publisher and package. There is no complete registry of every MBTiles file made by every publisher. FieldForge's product target is a maintained catalog of real worldwide datasets by layer and region, with exact version/date, measured file size, coverage, zoom levels, attribution, license, and checksum.

The active desktop readers open supported raster MBTiles (PNG, JPEG, WebP) and gzip-compressed Mapbox Vector Tile MBTiles (`format=pbf`). Vector features are drawn offline with a built-in basic preview style covering common water, land, buildings, roads, boundaries, rails, and points. The renderer places a bounded set of labels from names embedded in point, line, and area features, including basic overlap suppression. Publisher style JSON, filters, fonts, sprites, glyphs, multilingual rules, and curved-line label placement are not applied, so this is not full MapLibre cartography. A visually tiled map also is not a turn-by-turn routing graph.

The user-shared Wave 5 collection contains four real OSM regional archives for Kansas, Nebraska, North Dakota, and South Dakota: 1,558,226,547 bytes of ZIP downloads (about 1.45 GiB) and 3,644,960,240 bytes expanded (about 3.40 GiB). Their prepared `.ffmap` SQLite indexes report 5,226,766 features, including 370,827 objects with address tags. The collection marks these files `verified-download`, `installed_on_device: not-checked`, and `validated_navigation: false`. They are **not MBTiles** and have no prepared road graphs. The Maps tab includes a separate local `.ffmap` viewer that imports the index from a regional ZIP package; the current portal still does not host `.ffmap` files. The four state packages do not constitute complete U.S. coverage. The South Dakota archive was independently checked here against its catalog SHA-256; the other three payload files were not independently re-downloaded in this workspace.

## Sources that can build real coverage

| Coverage need | Source | Cost and rights | Current status |
| --- | --- | --- | --- |
| Worldwide streets, places, land and water base | OpenStreetMap data from Geofabrik or the OSM planet service, processed into tiles by FieldForge | Source data is openly downloadable. OSM data uses ODbL and requires attribution; comply with share-alike rules for derivative databases. Do not bulk-download or prefetch from OSM Foundation's standard tile servers. | Real source-data path; no global MBTiles package built or tested in this branch. |
| Ready-made global street vectors | OpenMapTiles / MapTiler global OSM vector datasets | MapTiler On-prem Custom is quote-only for B2C/B2B and lists premium MapTiler Planet. The exact license must explicitly allow FieldForge offline use and redistribution to its customers. | **Purchase hold.** Vector rendering is a prerequisite. |
| Global satellite background | MapTiler global satellite MBTiles and high-resolution on-prem imagery | Published medium-resolution pack is WebP raster MBTiles, sourced from 2020–2021 imagery. High-resolution on-prem terms require a tailored quote. | **Purchase/quote hold.** Raster display is supported; package-specific coverage, current price, and customer redistribution rights remain unchecked. |
| U.S. marine charts | NOAA Chart Display Service | Public regional MBTiles; baseline packages are updated weekly. Chart coverage is marine-focused and U.S.-only, not worldwide street or land mapping. | Free source candidate; not yet imported or checked in FieldForge. |

## Paid purchase queue for Chris

1. **MapTiler On-prem Custom, including MapTiler Planet global vectors.** Ask for an annual written quote and terms covering a paid consumer FieldForge product, offline use, customer downloads, update redistribution, attribution, storage/hosting, and activation without recurring user connectivity. Their published On-prem Standard price is **$2,500/year**, but its terms limit use to one internal production app and a maximum of 500 monthly active users; it expressly excludes B2C/B2B, so it is not the right purchase for FieldForge distribution.
2. **MapTiler global high-resolution satellite imagery.** Request a separate quote and written offline/customer-redistribution permission. The global medium-resolution WebP MBTiles is a lower-resolution, older (2020–2021) candidate; it should not be described as current high-resolution imagery.
3. **Optional licensed country or high-detail regional packs.** Decide only after global vector rendering is implemented and after each quote confirms exportable MBTiles (or a supported delivery format) and the exact FieldForge resale rights.

No purchase, vendor inquiry, account creation, or third-party message has been made. Do not use MapTiler's free tier for a paid customer product: it is marked non-commercial/evaluation, capped at 100 MAU, and uses older OSM vectors (2020) and satellite (2016).

## Work required before calling worldwide maps delivered

- Expand the basic vector preview toward a reviewed offline cartographic style. Point, line, and area names now receive bounded local labels with overlap suppression; continue with stronger multilingual font coverage, line-following placement, and source style assets where licensing permits. Validate more publisher schemas and uncommon MVT geometry cases.
- Build a versioned world overview plus downloadable country/region/detail packages. Keep data packages outside Git history; test download size, free-space needs, cancellation, checksum, extraction, rights metadata, and offline reopening.
- Add raster terrain, hydrography, relief, and lawful aerial/satellite layers where separately available. Report gaps and source dates instead of filling them with invented coverage.
- Keep routing data and route-engine validation separate from display tiles; never label a map tileset as route-ready.
- Populate the portal catalog only after actual files and redistribution rights are verified. The current online catalog can be empty, and the site has not been publicly hosted.

## Primary sources

- [OpenStreetMap Foundation tile policy](https://operations.osmfoundation.org/policies/tiles/)
- [OpenStreetMap ODbL guidance](https://wiki.openstreetmap.org/wiki/ODbL/License/Transition/Guidance_To_Data_Consumers)
- [Geofabrik free OSM extracts](https://download.geofabrik.de/)
- [OpenMapTiles generation and attribution](https://openmaptiles.org/docs/generate/generate-openmaptiles/)
- [MapTiler global OpenStreetMap vector tiles](https://www.maptiler.com/on-prem-datasets/dataset/osm/)
- [MapTiler global satellite medium-resolution MBTiles](https://www.maptiler.com/on-prem-datasets/dataset/satellite-2021/)
- [MapTiler high-resolution satellite licensing](https://www.maptiler.com/satellite/)
- [MapTiler On-prem pricing and license limits](https://www.maptiler.com/data/pricing/)
- [NOAA regional nautical MBTiles](https://distribution.charts.noaa.gov/ncds/index.html)
- [MBTiles specification](https://github.com/mapbox/mbtiles-spec)
