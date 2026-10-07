# Map integration status — 7 October 2026

This is the record of a tested local integration, not a published application.
The documentation checkpoint contains only five guide/status files.

## Implementation and publication

| Item | State |
| --- | --- |
| Tested implementation commit | `fe70c8bf919806ed833e8115e19115fac6412d43` |
| Tested implementation tree | `092c2f5c03c11e53c7b97be4b411e1fec3fcda31` |
| Shared development branch | `chatgpt/offline-knowledge-foundation` |
| Development head at this checkpoint | `669d0ff68b6df0ed8fcf7052336315183567882c` |
| Documentation checkpoint | `chatgpt/atlas-guides-recovery`, based on `669d0ff`, documentation only |
| Atlas payload | Present in the tested local source and verified wheel; not durably uploaded to GitHub |

Automatic approval review rejected publication of four normalized-MBTiles source
files because it did not recognize user authorization for that write.
Source publication remains pending approval. This documentation checkpoint
contains no source changes or map payloads and does not bypass that approval.

The atlas binary upload stalled and was interrupted. No atlas recovery branch
or commit was created; two uploaded immutable text blobs do not constitute a
saved atlas package. A complete source ZIP and the four-file normalized-MBTiles
review patch are the planned review handoff while publication remains pending.
Independent recovery branches do not establish a combined released build.

## Included data and implemented behavior

- **615 overview tiles:** zooms 0–3 world overview and zooms 4–6 U.S./territory
  overview. Generalized Natural Earth 1:50 million land, state outlines,
  selected city labels, rivers and lakes; no street detail or terrain elevations.
- **777 selected town points:** a separate Natural Earth 1:10 million selection.
  Main Maps can search and open the atlas at a chosen town with a clearable
  temporary marker. The GPS finder loads included towns and centers a reference
  marker on its current map/outline, pausing receiver following.
- **Local map formats:** indexed flat and supported normalized `map`/`images`
  MBTiles, PNG/JPEG/WebP raster display, and basic gzip MVT/PBF vector previews.
  The portal's MBTiles publisher remains flat-only.
- **Regional preparation:** `.ffmap` display/search indexes, regional ZIP index
  import and local OSM PBF preparation remain available. These are not routing
  graphs; the portal does not distribute these indexes or extract their ZIPs.
- **Online/saved routes:** explicitly configured portal address lookup, verified
  map downloads and provider-calculated driving alternatives; saved directions,
  planned geometry and GPX export remain available after disconnection.

No complete U.S. street database, complete settlement/address directory, or new
offline routing engine/graph is bundled. Basic vector previews do not apply
publisher styles, fonts or sprites. Small islands and features may be omitted.
See [bundled atlas](BUNDLED_ATLAS.md), [its verification record](BUNDLED_ATLAS_VERIFICATION.md),
[Offline Maps](OFFLINE_MAPS.md) and [the regional data plan](GLOBAL_MAP_DATA_PLAN.md).
Dataset versions, rights and checksums are in
`fieldforge_gps/data/USA-OVERVIEW.json` and `USA-OVERVIEW-RIGHTS.txt`.

## Fresh verification

| Check | Observed result |
| --- | --- |
| Selected headless integration suite | **976 passed in 23.40 seconds** |
| Installed-package comparison | **151 installed runtime/data/portal files exactly matched source** |
| Offline installed-package exercises | Normalized MBTiles, JPEG/WebP, the 615-tile atlas, 777-town catalogue and disconnected portal checks passed with sockets forbidden |
| Static checks | Whole-tree Ruff and whitespace checks passed |
| Python 3.10 syntax | **136 runtime files** parsed with 3.10 syntax rules; runtime execution on 3.10 was not established |

The readers retain full before/after metadata checks within each API.
Windows path/descriptor timestamp differences are handled without weakening
POSIX comparisons. Regression coverage includes metadata drift, actual writes
and file replacement; this does not make local files tamper-proof.

## Pending

Publication approval and final assembled source/data verification remain pending.
GUI workflows and Windows execution have not passed for this snapshot.
Physical receiver accuracy, live provider operation and native mobile behavior
also require their own checks. The socket-forbidden checks establish offline
behavior only; they are not a live portal/provider test. Update this record after
publication and those execution checks complete.
