# Bundled offline reference library

FieldForge ships **267 articles, approximately 363,255 words, across 14 categories**.
The article pack is about 2.65 MB uncompressed. The corpus is included in the wheel,
so installation, browsing and search require no network, model or external service.
An empty desktop library installs it automatically. Existing users can choose
**Install Reference Library**, or run:

```bash
fieldforge-blueprints --database fieldforge.db install-library
```

This reuses the existing transactional knowledge-pack importer. Repeating the
install is idempotent; private notes/bookmarks survive. Conflicting user-modified
articles are not replaced: the entire installation aborts, preserving prior data.
Normal pack import/export remains available for a deliberate replacement workflow.

## Coverage

| Category | Articles | Included subjects |
| --- | ---: | --- |
| Survival | 11 | Emergency situations, fire, shelter, signals, water, kits |
| Agriculture | 10 | Soil improvement, irrigation, compost, growing locations and beds |
| Water and sanitation | 9 | Drinking water, disinfection, distillation, rain barrels and scarcity |
| Medicine | 24 | First aid and physiology references |
| Science | 36 | Biology, chemistry, physics |
| Measurement | 36 | Algebra, geometry, trigonometry |
| Engineering | 37 | Statics, measurement, tables, engineering design and history |
| Manufacturing | 7 | Woodworking, hand tools, sharpening and workshop maintenance |
| Energy | 24 | Circuit theory, electronics, batteries |
| Communications | 12 | Radio concepts, receivers, modulation, antennas and media |
| Computing | 24 | Operating systems, files, concurrency, Python |
| Software | 13 | Software engineering and embedded systems |
| Projects | 12 | Scope, schedule, cost, quality, risk and communications |
| Education | 12 | Learning theories and organizational knowledge |

This is a broad initial reference collection, **not complete coverage of survival
or civilization rebuilding**. The category labels describe indexing, not a verified
curriculum. Sanitation procedures, metalworking, industrial manufacturing, modern
medical protocols, public-health infrastructure, civil construction, energy system
design and many other subjects still need dedicated, technically reviewed packs.
Some pages are introductory or index-oriented; books are selected excerpts, not
complete books. Equations and tables may be harder to interpret in plain text.

## Sources, licensing and review status

Text is adapted from English Wikibooks. Every article preserves:

- Original title, contributor attribution and contributor-history URL.
- The exact source revision URL (`oldid`) and body SHA-256.
- CC BY-SA 4.0 licensing information and the text adaptation notice.
- An empty FieldForge review date, accurately indicating no independent review.
- A caution or high-stakes label, separate from technical validation.

The article text is a plain-text adaptation under
[Creative Commons Attribution-ShareAlike 4.0](https://creativecommons.org/licenses/by-sa/4.0/),
following [Wikibooks' copyright policy](https://en.wikibooks.org/wiki/Wikibooks:Copyrights).
Images are omitted; available image/formula alternative text is retained. Navigation
and layout are converted. Rights checks exclude explicit conflicting-rights markers,
but they are not a legal audit of each contribution. Preserve attribution, license,
change notices and applicable share-alike terms when redistributing adapted content.
Article licensing does not license FieldForge's application code.

Community content may be incomplete, inaccurate, old or locally inapplicable.
These are archived references, not independently validated medical, structural,
electrical or drinking-water instructions. Retrieval and AI citation checks do
not establish factual support or safety. No article is silently promoted to a
reviewed status by import or generation.

## Maintenance

- `fieldforge/content/packs/reference-library.json`: one checksummed, atomic pack;
  no duplicate category copies.
- `fieldforge/content/packs/catalog.json`: full title/revision/history/hash inventory,
  word counts and acquisition failures.
- `fieldforge/content/LICENSE_CONTENT.txt`: redistribution notice.
- `tools/build_reference_library.py`: explicit network acquisition tool, never
  imported or executed during application startup.

To refresh from upstream, use a new cache directory and review the resulting diff:

```bash
python tools/build_reference_library.py --output fieldforge/content/packs --cache ../reference-cache-new --per-book 12
pytest tests/test_reference_library.py
```

Reusing an existing cache preserves previously fetched responses. The catalog
pins the shipped articles to exact revisions; a refresh with a new cache deliberately
selects current revisions. Remote HTML rendering can change independently of page
revisions, so a fresh rebuild is not asserted to reproduce identical body hashes.
The checked-in pack is the reproducible install artifact.

Before shipping updates, inspect selected titles and text conversions, confirm
licenses and attribution, verify every catalog/body checksum, run the offline
installation/conflict/idempotency tests, and test an installed wheel outside the
checkout. Domain review should prioritize emergency content and record reviewers,
evidence, locale and expiration policy in a future reviewed-content schema. Keep
unreviewed and reviewed collections visibly distinguishable.
