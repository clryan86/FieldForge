# Portal publishing and package notes

The portal is a short preparation stop for an offline application. The home
page reserves sections for the program's resources while maps remain the active
implementation priority. A label or draft plan is not an available download.
No public hostname, production provider, billing account or paid entitlement is
created by this code change. Operators must configure and deploy their portal.

## Present behavior

- Starting FieldForge, reopening this workspace or regaining network access
  does not connect it automatically. **Connect** presents a warning with the
  destination and defaults to **No**. Only approval starts a portal request.
- After a successful explicit desktop connection, the configured portal home
  opens in the browser. A copyable URL and **Open portal home** button provide
  a fallback. Health checks never reopen it. Browser launches send no selected
  address, household information, coordinates or consent token in the URL.
- The browser home is already a network page. Its separate confirmation starts
  API access, not the computer's internet connection. The desktop's approval is
  deliberately not transferred through URL parameters or browser storage.
- Both surfaces retain selected coordinates, loaded routes and map metadata
  through a disconnect. New provider requests and map transfers require an
  explicit connection. Closing the browser loses unsaved session results.
- Map entries show actual size, format, coverage, version and provenance. Local
  filters and size sorting do not make requests. Browser results use pages of
  24 cards so a large catalog does not build thousands of cards at once.
- Immutable map publishing and the inventory builder use the same validator,
  hash calculation and provenance schema. They never fetch public map tiles.
- Prepared regional `.ffmap` indexes now use that publisher and download path,
  including compatibility catalogs, byte-range retry, and mixed download lists.
  Browser/native filters identify them separately, and desktop opening uses the
  regional display/search viewer. The 4 GiB, nonempty, closed-database preflight
  preserves each file and its embedded source receipt. Available regions still
  depend on supplied, permitted files; this change includes no state packages.
- Browser and native desktop map lists retain up to 100 selections across
  filtering and disconnection and show their combined size. A saved JSON list
  can be imported offline and downloaded explicitly from its original portal.
  Sequential downloads preserve completed files; retry verifies and reuses
  matching local copies. Lists do not enable billing or bypass map licenses.

## Reserved home-page sections

Each card's **What will be added** note identifies its intended contents. Before
replacing a placeholder with a download, check actual import compatibility,
source/redistribution rights, version, bytes, SHA-256 and offline instructions.

| Home section | Publication work to resume |
|---|---|
| Maps & images | Publish permitted prepared `.ffmap` regional indexes, MBTiles, and image maps; show actual coverage and useful detail. Add a reviewed source directory when distribution terms are established. |
| Routes & address lookup | Operate permitted routing/geocoding services. Keep user requests explicit and retain provenance in offline exports. |
| Knowledge Library & Ask Library | Build reviewed topic bundles compatible with the existing library import workflow; supply manifests and local search instructions. |
| Foundations & Civilization Pathways | Package original lessons, activities and licensed references by subject, level and language. |
| Original documents & PDFs | Provide approved documents with full sources, revisions and licenses. Disclose extraction limitations. |
| Pocket Library & Reading Links | Package portable reading collections with local links and provenance. Do not upload personal reading history. |
| Emergency Mode & Action Cards | Publish reviewed regional references and dated action-card sources. Household contacts and plans stay local. |
| Household & Supplies | Provide blank inventory/supply templates and appropriately licensed guides. |
| Power Planner & Inventory | Publish blank energy worksheets and compatible equipment references, with units. |
| Field Binder | Curate printable source packs; personal binder exports remain local. |
| Recreation | Add original or licensed games, activities and reading, labeled by language and needed equipment. |
| Places & GPS | Add licensed regional place CSVs and GPS guides; keep private places and tracks local. |
| Backup & Recovery | Publish version-matched recovery instructions and empty verification checklists. |
| Application downloads & updates | Link reviewed release artifacts and release notes; obtain signing/release infrastructure before promising signed installers. |

## Proposed revenue model, not a legal determination

Prefer one-time delivery allowances over requiring subscriptions to open saved
files. Tentative labels are **Essentials** (a free starter collection),
**Regional** (10 GiB per purchase) and **Field Library** (50 GiB per purchase).
The two amounts are planning examples, not active quotas or promises. Prices
need bandwidth, storage, provider, support, payment and tax costs before launch.
The paid service would be curation, preparation and permitted distribution;
content remains subject to its own license and recipients' existing rights.

Licensing must be evaluated per asset, including map styles, tiles, imagery,
documents and embedded third-party materials. A publicly accessible file is
not automatically redistributable or sellable. Noncommercial material must not
be included in a paid pack without appropriate separate permission. Retain
required attribution, license copies, modification notices and applicable
share-alike offers. An attribution text box does not prove those permissions.

Primary references checked 2026-10-04:

- [OpenStreetMap copyright and license](https://www.openstreetmap.org/copyright):
  distribution and adaptation come with ODbL attribution/license obligations.
- [OSMF tile policy](https://operations.osmfoundation.org/policies/tiles/):
  `tile.openstreetmap.org` prohibits offline prefetch and bulk tile archives.
  Use our own tiles or a provider whose agreement expressly permits this use.
- [Creative Commons FAQ](https://creativecommons.org/faq/): check the specific
  license, including restrictions on commercial use and additional rights.

Before any paid launch, obtain jurisdiction-specific advice from qualified
legal/tax professionals on the operator's location, customer markets, copyright
and database rights, consumer/refund requirements, taxes and privacy. Define
plain purchase terms: exact bytes, GB vs GiB, expiry (if any), failed/retried
downloads, interrupted transfers, refunds and updates. Do not infer these rules
from a generic license or this engineering note.

## Implementation gates for future sales

1. Verify rights and supplier contracts; publish usable licensed packs first.
2. Measure actual hosting/provider costs and set reviewed prices and allowances.
3. Define account and receipt recovery without collecting household data.
4. Use a hosted payment service; verify signed webhooks and idempotent orders.
   Entitlements and byte accounting must be enforced by the server, never by
   hiding links in the browser. Never store payment-card details in FieldForge.
5. Map lists now offer byte-range resumption with verified partial checkpoints,
   explicit retry and offline discard controls. Completed files are also
   verified and reused on a list retry. Specify charging for retries before
   enabling metering; selection totals are not a billing ledger.
6. Test interrupted and duplicate requests, refund/revocation flows and privacy
   retention. Already downloaded files must remain usable without online checks.
7. Only then replace the draft tier text with actual terms and purchase controls.

Coordinate discovery now uses numeric WGS 84 catalog bounds in the native map
tab and browser portal. Address results can fill the map filters locally, and
loaded catalogs stay filterable offline. Text-only coverage is counted separately
and excluded from coordinate matches; bounds are candidate extents, not verified
tile completeness. Regional inventories should provide real numeric extents and
document their useful zoom/detail coverage.

Regional publication support is now implemented for prepared `.ffmap` files.
Next work is to supply and verify actual regional inventory files and complete
usable content-pack import contracts. Leave the knowledge placeholders until real bundles
and their import contracts are ready; do not populate a catalog with fake files.
