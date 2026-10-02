# Three offline blueprint makers

The library now includes a bundled reference collection and three distinct design
workflows. Open **Knowledge Library → Blueprint Makers**, or run
`fieldforge-blueprints --database fieldforge.db gui`.

| Maker | Inputs | Outputs and local checks |
| --- | --- | --- |
| Engineering | Brief, dimensions, constraints, available materials/tools, evidence keywords | Dimensioned assembly views, isometric wireframe and individual part sheets; parts/materials tables and CSV; ordered build steps; assumptions; fixed-formula calculations with exact units; risks and requirement acceptance checks |
| Project | Outcome, time/budget constraints, people/resources, evidence keywords | Phases, deliverables, resources, dependency schedule, illustrated step guide, risks and acceptance checks; rejects cyclic or unknown dependencies |
| Software | Capabilities, offline constraints, data, technology/resources, evidence keywords | Components, interfaces, data flows, trust zones, storage, authentication assumptions, decisions/alternatives and implementation steps; validates component references and requirement coverage |

All three produce **drafts**, never an approved or certified status. Engineering
drawings show axis-aligned rectangular part envelopes in millimetres, not detailed
fabrication geometry, CAD solids, joint designs, load certification or code approval.
An empty or incomplete geometry can be retained as a draft needing revision.

## Install and use

```bash
python -m pip install -e .
fieldforge-blueprints --database fieldforge.db install-library
fieldforge-blueprints --database fieldforge.db gui
```

Opening an empty desktop library installs the packaged references locally in a
background worker. An existing library has an **Install Reference Library** button.
Installation uses the existing transactional knowledge-pack importer: identical
articles are skipped, different articles with the same slug abort the entire
installation, and private notes remain intact. Nothing is downloaded at startup.
See [the reference collection](REFERENCE_LIBRARY.md) for coverage and limitations.

For AI generation, follow [local Ollama setup](LOCAL_ASSISTANT.md), including
disabling cloud features in the **server** process. Choose a local completion model
that supports Ollama JSON-schema structured outputs. The model and Ollama are
separate installations; transfer both before going offline. No model is bundled,
selected automatically, or downloaded by FieldForge. A missing model leaves the
library, saved designs, manual editing and exports available.

1. Choose a maker, describe the intended result, and enter constraints and resources.
2. Inspect **Requirements → Source evidence → Preview current request** before
   loading a model. Optional evidence keywords help narrow lexical retrieval.
   The preview needs no model or network; private library notes are never included.
   Then load installed models and select one for generation.
3. Generate. The status shows retrieval, design, repair when needed, and critique.
4. Inspect **Blueprint and checks**, the source excerpts, and **Drawings**. The text
   view provides an accessible equivalent to diagrams. Keyboard arrows and Page
   Up/Down scroll the drawing canvas. Choose **Fit width**, **100%**, **150%** or
   **200%** to inspect details; Left/Right pan horizontally and Home returns to
   the upper-left corner. Both scrollbars remain available.
5. Edit the canonical JSON in **Edit design**, then **Apply edits and recompute**.
   Edits invalidate the earlier model critique. Unapplied edits cannot silently
   disappear into a save/export of the old version.
6. Save a `.json` design or export a new directory containing `report.html`,
   `blueprint.json`, SVG drawings and a README. Reports print from a browser and
   work entirely offline, with no scripts, fonts, images or assets fetched remotely.

### Engineering drawing package

Engineering exports derive every drawing and schedule from the same saved design:

- `top.svg`, `front.svg`, `side.svg`: occupied assembly spans in both view axes,
  with extension lines, dimension ticks and explicit axis directions. The minimum
  corner is reported separately; translating an assembly does not add unused
  origin space to its dimensions. Acceptance span checks use the same bounds.
- `isometric.svg`: a wireframe overview of all rectangular envelopes. Obscured
  edges remain visible; this is not hidden-surface removal. A separate envelope
  inspector reports intersections and contact without inferring physical solids.
- `part-001.svg` through `part-060.svg`, as needed: one sheet per recorded part,
  three independently fitted projections, XYZ size and minimum-corner position,
  material, source IDs and a design checksum prefix. The numeric filename follows
  the current parts-list order; the part's own ID remains the revision identity.
- `parts.csv`: one row per placed instance, exact recorded dimension values,
  material, position, source IDs and corresponding detail-sheet filename.
- `materials.csv`: the recorded quantities, units, specifications and part/source
  references. Similar parts are not silently combined and stock quantities are
  not inferred from part dimensions. These are not cut lists.

White drawing backgrounds support printing. Use dimension values: the sheets are
not printed to a physical scale, and thin or small geometry may be subpixel at a
given zoom. Assembly numbers refer to the parts schedule; labels can be absent or
obscured in crowded views, so use the individual sheets and complete text tables.
The self-contained HTML report has a sheet index, accessible tables, full source
excerpts and print page breaks. A draft with missing/zero dimensions remains
visibly incomplete and retains its blocking validation results.

CSV files are UTF-8, with quoted multiline fields. Formula-like text receives a
leading apostrophe for spreadsheet safety. The canonical JSON and HTML retain
the original text. CSV schedules are export-only and are not accepted as imports.
Existing version-1 blueprint and project files need no migration: reopening and
exporting them regenerates the new sheets without changing the saved design.

This package does not introduce tolerances, joints, fastening details, machining
operations, nesting, stock allowances, structural analysis or fabrication CAD.
Those require additional structured geometry and independently reviewed rules.

### Inspect envelope intersections and contact

In **Drawings → Geometry inspector**, filter pairs by overlap, face contact,
edge contact, point contact or separation. Select a pair to read its per-axis
overlap and gap lengths. **Show pair in drawing** highlights both envelopes in
the isometric view; **Clear highlight** removes the selection. Inspection does
not edit the design, change its evidence or add a project revision. Applying an
edit, opening a design or restoring a revision recomputes the analysis.

All pairs are checked, up to 1,770 for the 60-part limit. Classification uses
decimal arithmetic on the recorded numeric values, with no assumed fabrication
tolerance. A part ending at `0.1 + 0.2` mm touches one starting at `0.3` mm;
a recorded start at `0.30000000000000004` mm retains the tiny positive gap.
Results are deterministic by part ID. Missing parts, duplicate IDs or zero-size
parts make the whole analysis **unresolved**; partial results cannot look clean.

Positive overlap on all three axes is an envelope intersection. Zero overlap on
one, two or three axes gives face, edge or point contact respectively, provided
no axis has a gap. Groups include chains of any contact or intersection. This
does not prove a physical connection, joint, load path, strength or stability.
Bounding volumes can intentionally intersect, and separate groups can describe
separate assemblies, so these observations are warnings by default.

Add explicit limits under **Requirements → Acceptance limits** when the intended
design requires them. Supported count metrics are `geometry.overlap_pairs`,
`geometry.connected_groups` and `geometry.face_contact_pairs`. For example,
`geometry.overlap_pairs = 0` requires no intersecting envelopes; a connected-group
limit of 1 requires one touching/overlapping group, not a verified structure.
These user-owned limits persist through refinement, trigger the bounded repair
pass when failed, and remain blocking if failed or unresolved. A favorable model
critique cannot override them.

Every engineering export includes `geometry.json`, with the design checksum,
scope, summary, groups and all pair relations, and `geometry.csv`, with exact
decimal-string overlap/gap lengths in millimetres. An unresolved or single-part
CSV contains an explicit status row instead of pair rows. The HTML report shows
the summary, groups and all touching/overlapping pairs. These derived files are
recomputed on export, never trusted as saved checks and never imported as designs.

Inspect an existing blueprint without a library database, model or network:

```bash
fieldforge-blueprints geometry shelf-draft/blueprint.json
```

The command exits 0 when analysis completed (even if intersections were found),
1 for unresolved geometry and 2 for invalid input or another maker. Use `check`
to obtain the overall draft/needs-revision result including your acceptance limits.

### Preserve clearance between specific parts

Choose a pair in **Geometry inspector → Set clearance limit for selected pair**.
This opens the acceptance form with Part A and Part B filled in. Enter the required
distance yourself, then **Add limit** and **Apply limits to design**. The shortcut
does not invent a minimum, apply a rule, or modify a project. You can also choose
part IDs from the editable form lists, or type intended IDs before generation.

Pair rules use a target such as `P1/P2`: two distinct, case-sensitive part IDs.
Either order identifies the same pair. The five measurements are:

| Metric | Unit | Meaning |
| --- | --- | --- |
| `pair.clearance` | mm | Shortest 3D Euclidean distance between the two rectangular envelopes; zero for contact or overlap |
| `pair.gap_x` | mm | Nonnegative gap between their X-axis projections |
| `pair.gap_y` | mm | Nonnegative gap between their Y-axis projections |
| `pair.gap_z` | mm | Nonnegative gap between their Z-axis projections |
| `pair.relation` | text | Exact `overlap`, `face_contact`, `edge_contact`, `point_contact` or `separated` |

Numeric pair rules support `<=`, `=` and `>=`; relation rules require `=`.
Missing, renamed or ambiguous target parts, or unresolved envelope analysis, cannot
satisfy a rule. User-owned rules persist through generation, repair, refinement,
manual edits, saving, exporting and project restoration. Failed/unresolved rules
remain blocking regardless of a favorable model critique.

For example, two boxes with 3 mm and 4 mm gaps along X and Y have 5 mm shortest
clearance. This is geometric distance only: it does not prove an accessible route,
usable maintenance volume, thermal/electrical isolation or a suitable physical joint.
No recommended minimum is inferred from a material, hazard or source title.
A zero axis gap can mean overlapping projections; use `pair.relation` when a
particular kind of contact is required. Contact alone does not verify fastening.

```json
[
  {"id":"C1","label":"User-specified service gap","metric":"pair.clearance",
   "target":"P1/P2","operator":">=","value":5,"unit":"mm"},
  {"id":"C2","label":"Expected face contact","metric":"pair.relation",
   "target":"P1/P3","operator":"=","value":"face_contact","unit":"text"}
]
```

Pair numeric comparisons use exact decimal values without the legacy arithmetic
epsilon. Shortest clearances are compared as squared distances, avoiding square-root
rounding at a threshold. The displayed square root uses up to 17 significant digits
and is labeled approximate when rounded. Pair numeric `actual` values are decimal
**strings** in computed results; shortest clearance also includes
`actual_squared_mm2` and `actual_is_rounded`. For example, a displayed approximate
1 mm can still fail `<= 1 mm` when its exact square exceeds 1 mm².

The geometry inspector displays shortest clearance. Each JSON/CSV pair record adds
`clearance_mm`, `clearance_squared_mm2` and `clearance_is_rounded`; CSV data rows
retain the existing columns. The HTML report places a compact acceptance summary
before drawing sheets and retains full recomputed comparison details below them.
Original version-1 design/project files need no migration; older builds cannot
validate the newly introduced rule metrics.

### Inspect source evidence without a model

The source preview searches the brief, constraints, resources, evidence keywords,
pending change instructions and text-valued acceptance limits. Select a result to
read the exact passage, character offsets, body checksum, source URL, attribution,
license, review status and matched request fields. Search diagnostics report fields
with no selected match and fields whose query terms were truncated. These are
lexical matches, not a judgment that the source supports every claim in that field.

Preview does not change the current draft or append project history. Generation
searches again against a fresh snapshot; changed requirements or library content
can change the results. **Show design sources** displays the original excerpts
saved with the current design and labels them as a historical snapshot.

### Refine and preserve a project

After generating or opening a design, choose **Project and revisions → New project**
and save a `.ffproject.json` file. The first design becomes revision 1. While that
project is open, successful generation, AI refinement and applied manual edits
automatically append revisions. A draft already changed in memory is preserved
before the next change. **Save revision** can also record the current design.

Use **Refine with AI** to describe a change such as “reduce the width to 600 mm” or
“add a backup verification phase.” The current Requirements fields and existing
design enter the request. The model is instructed to preserve unaffected IDs and
requirements, but that behavior still requires review. The new result goes through
the same schema checks, bounded repair and critique as an initial design. It also
records the requested change and a canonical SHA-256 fingerprint of the previous
blueprint in its request metadata; older saved blueprints remain readable.

The comparison view lists changed fields, matching parts, phases and components by
ID rather than array position. Select a saved revision to compare it with the current
draft. **Restore selected** appends a new revision containing that design; history
is retained. **Undo last draft change** returns to the preceding in-memory draft,
also recording a new revision when a project is open. It requires no model.

Project records contain the complete design, original source excerpts, request,
model critique, timestamp, change note and linked checksums. Invalid history is
rejected. Reopening recomputes validation; hashes detect accidental modification,
not authenticity or expert approval. A restored historical design is not checked
against newly edited library articles until another AI generation/refinement.

Saving uses an atomic replacement, an advisory OS file lock and an expected-head
check. Two FieldForge windows cannot silently overwrite each other's newer revisions.
If a save conflicts or fails, the new draft remains in memory and the existing
project file remains intact. Save that draft separately, then reopen the project
or create a new project. Cooperating local processes and ordinary local filesystems
are the supported concurrency case; externally edited files and network filesystem
locking are not guaranteed. Power-loss durability still depends on the filesystem.

A project is limited to 100 revisions and 32 MiB; individual designs remain limited
to 2 MB. At the limit, start another project from the current design. Copy the
`.ffproject.json` file to back up or transfer its entire history. These project files
are **separate from FieldForge's database snapshot backups**. The neighboring `.lock`
file has no project content and need not be transferred; OS locks release when a
process exits, even if the empty sidecar remains.

### Compare engineering outcomes across revisions

In **Project history**, select a revision to compare it with the current applied
draft. The comparison recomputes checks locally, without a model or internet
connection. It shows dimensions, materials and positions by stable part ID;
overall XYZ spans; envelope intersections and contacts; and exact changes in
pair clearances and axis gaps. Reordering parts does not change their identity.
Duplicate IDs make part matching unresolved. Empty or degenerate geometry makes
pair comparison unresolved, so it cannot appear to have eliminated collisions.

Every acceptance rule from the selected **baseline** is evaluated unchanged on
both designs. `regressed` means a previously passing rule now fails or cannot be
resolved. `now passes` means a previously failing or unresolved rule passes the
same criterion. Changed, removed and newly added rules appear separately, along
with results under the current rules. Lowering a minimum clearance from 5 mm to
2 mm cannot hide a revision that reduced the actual clearance from 5 mm to 2 mm:
it still regresses against the fixed 5 mm baseline. Changing a rule's label or reversing
the order of a pair target does not alter its criterion.

Clearance direction uses exact squared distances, including changes too small to
show in the rounded distance label. Changes in contact type remain visible even
when both clearances are zero. Spans use decimal arithmetic on recorded geometry.
Other acceptance metrics retain their existing evaluator behavior, including the
documented numeric epsilon. A larger gap or fewer contacts is not automatically
better; only explicit requirements establish the desired outcome. Checks cover
recorded envelopes and supported measurements, not structural performance.

**Export selected comparison** chooses a parent folder and creates
`comparison-revision-N-to-draft/`, refusing an existing folder. It checks pending
edits and recomputes from the selected revision and the applied draft at export
time. The original project is unchanged. The folder contains:

- `report.html`: readable offline report, requiring no JavaScript or remote assets.
- `comparison.json`: full computed results and all changed geometry pairs.
- `before.json` and `after.json`: complete, reopenable snapshots with freshly
  computed validation and canonical JSON SHA-256 identities in the report.
- `README.txt`: interpretation, hashing and completeness notes.

The readable view shows at most 200 changed pairs; the JSON retains them all
(up to 3,540 when two 60-part designs have entirely different IDs). Recorded
field differences are bounded to 200 entries and 2,000 characters per value;
both complete snapshots are supplied for inspection. An interrupted export may
leave an incomplete folder; retry with a new destination. The report compares
both snapshots with the current checker version, not historical checker behavior.

Project and software makers also receive fixed-baseline acceptance comparisons
and freshly computed validation. No aggregate quality score is inferred when
limits are absent, and passing checks never changes a draft into a certification.

```bash
# Preserve the original raw-field comparison unless --results or --output is used.
fieldforge-blueprints compare before.json after.json --results
fieldforge-blueprints compare before.json after.json --output revision-comparison
# Compare two immutable saved revisions directly, without a database or model.
fieldforge-blueprints project-compare shelf.ffproject.json 1 3 --output saved-comparison
```

These commands exit 0 when the comparison completes, even if it finds regressions;
inspect `acceptance.outcomes` and unresolved results. Invalid input exits 2.
Use `check` for the existing current-design acceptance exit status.

### Acceptance limits checked by the app

Open **Requirements → Acceptance limits** to add numeric limits or exact text
requirements. For example, set **Overall X span <= 600 mm**, **Dependency schedule
duration <= 10 day**, or require component `DB` to retain trust zone `device`.
Choose a measurement, enter its target ID when required, comparison and value,
then **Add limit**. Limits can be set before the first generation. For an existing
design, **Apply limits to design** records the changed requirements and recomputes
checks; in an open project this creates a revision. To change a limit, remove its
row and add its replacement, then apply. Pending limits cannot silently disappear
into a save/export or AI refinement. **Apply edits and recompute** applies both
the edited design and configured limits.

| Maker | Supported measurements |
| --- | --- |
| All three | Required requirement IDs and build/implementation step IDs |
| Engineering | Overall X/Y/Z envelope spans, individual part X/Y/Z sizes, exact part material text, part count |
| Project | Dependency schedule duration, individual phase duration and finish day |
| Software | Component count, required component IDs, exact component kind and trust-zone text |

Every rule is user-owned request data, outside the model's output schema. The
same application checks run on generation, bounded repair, manual edits, load,
restoration and reports. A failed or unresolved rule marks the draft
`needs_revision`, even if the model critique reports no findings. Missing or
ambiguous target IDs and invalid dependency schedules cannot pass. The model is
shown the failures during its one repair opportunity; it cannot remove a rule.
Refinement inherits applied limits unless the user explicitly changes them.
Changing limits invalidates the old model critique.

Overall span is the largest part endpoint minus the smallest part origin on
each axis; translating the entire layout does not change its span. Each part is
one instance. Schedule limits use relative dependency-only days, with parallel
phases overlapping; they do not guarantee staffing, procurement or calendar dates.
Text equality is case-sensitive and checks the recorded field, not whether the
material is suitable or the architecture actually enforces that trust boundary.
Numeric equality absorbs at most `0.0000001` of the metric's stated unit for
floating-point noise; it is not a fabrication tolerance. Limits use explicit
canonical units (mm, day, count or text), with no implicit conversion. Passing
limits does not certify the design or establish the truth of model-written values.

Up to 30 limits are supported. They travel inside saved blueprints and project
revisions; old blueprints without limits remain readable. Their actual values and
pass/fail/unresolved results appear in **Blueprint and checks** and offline reports.
The structured CLI `check` command also recomputes them and exits 1 for a draft
needing revision (0 for a draft with no blockers; neither means approved).

Saved files include the brief and selected excerpts; treat them as project records.
Saved status and calculation results are recomputed when loaded. Checksums detect
accidental changes, not authorship or malicious tampering. Saving may replace a
valid existing blueprint but refuses unrelated JSON, knowledge packs and databases.
Export refuses an existing directory. An interrupted export leaves a partial
directory for inspection, rather than deleting a user-selected directory.

## Command line

```bash
fieldforge-blueprints --database fieldforge.db generate engineering "Design a workshop shelf; identify missing load and material evidence" --evidence-query "woodworking statics" --model YOUR_LOCAL_MODEL --output shelf-draft
fieldforge-blueprints --database fieldforge.db generate project "Plan a community workshop with three volunteers over ten days" --evidence-query "project scope schedule risk" --model YOUR_LOCAL_MODEL --output workshop-plan
fieldforge-blueprints --database fieldforge.db generate software "Design an offline inventory system with SQLite and recoverable backups" --evidence-query "software file systems data" --model YOUR_LOCAL_MODEL --output inventory-architecture
fieldforge-blueprints export shelf-draft/blueprint.json shelf-copy
fieldforge-blueprints --database fieldforge.db refine shelf-draft/blueprint.json "Reduce the width to 600 mm and explain the changed assumptions" --model YOUR_LOCAL_MODEL --output shelf-revised
fieldforge-blueprints compare shelf-draft/blueprint.json shelf-revised/blueprint.json
fieldforge-blueprints project-init shelf-draft/blueprint.json shelf.ffproject.json
fieldforge-blueprints project-history shelf.ffproject.json
fieldforge-blueprints project-add shelf.ffproject.json shelf-revised/blueprint.json --expect HEAD_CHECKSUM_FROM_HISTORY --note "Width revision"
fieldforge-blueprints project-restore shelf.ffproject.json 1 --expect CURRENT_HEAD_CHECKSUM
fieldforge-blueprints project-export shelf.ffproject.json restored-report --revision 1
fieldforge-blueprints acceptance-metrics engineering
fieldforge-blueprints apply-limits shelf-draft/blueprint.json limits.json shelf-with-limits
fieldforge-blueprints check shelf-with-limits/blueprint.json
fieldforge-blueprints --database fieldforge.db evidence engineering "Lay out a rain barrel" --resources "threaded fittings" --constraints "mosquito exclusion"
```

For CLI generation, add `--limits limits.json`. Refinement preserves existing
limits by default; `--limits` explicitly replaces the list, and a file containing
`[]` explicitly clears it. The file is a UTF-8 JSON list (maximum 64 KiB) with
unique IDs; duplicate JSON keys, unknown measurements, unsupported units and
non-finite values are rejected. Example:

```json
[
  {"id":"L1","label":"Fit the available width","metric":"envelope.x",
   "target":"","operator":"<=","value":600,"unit":"mm"},
  {"id":"L2","label":"Keep the inspection step","metric":"step.exists",
   "target":"Inspect","operator":"=","value":1,"unit":"count"}
]
```

`acceptance-metrics MODE` lists valid keys, units and target types. Retention
rules use `= 1`; text rules use `=`; numeric limits use `<=`, `=` or `>=`.
`apply-limits` creates a new export and leaves the source file intact. Applying
limits, checking a saved draft and listing metrics require neither a model nor
a library database.

`python -m fieldforge.blueprints` is equivalent. Options include `--constraints`,
`--resources`, `--evidence-query`, `--port` and `--timeout` (maximum 300 seconds per
model call). A run makes two model calls, or three when repair is needed. Cancellation
closes FieldForge's request; Ollama may take additional time to release its GPU.

## Generation and validation pipeline

1. Build a disposable in-memory passage index from one consistent, checksum-checked
   library snapshot. Paragraph/sentence-aware overlapping windows preserve exact
   offsets and stay within 1,100 characters. FTS5 BM25 with Porter stemming ranks
   passages; an exact-token Unicode-normalized BM25 fallback works without FTS5.
   Request fields contribute up to 96 distinct non-stopword terms each in bounded
   queries. Longer fields retain their first and last 48 terms and report truncation.
   Reciprocal ranks are fused per field, with a coverage bonus and article diversity
   penalty. Select at most eight excerpts and two per article, excluding identical
   text and heavily overlapping windows. Multiple useful sections of one article
   can now survive selection. Metadata-only matches cannot supply a body passage.
   This is lexical retrieval, not embedding-based semantic search. It preserves
   article offsets, attribution, license, review status and source checksum.
   Refinement remaps prior citations only when the current excerpt and article
   checksum match exactly; changed or unretrieved support is explicitly removed.
2. Send the request and excerpts as data with a mode-specific bounded JSON schema.
   Ollama's `format` constrains output syntax. A local validator independently
   checks shape, finite numbers, units, references, graph consistency and coverage.
3. If needed, make at most one repair request with the observed failures. Truncated
   or malformed final designs are rejected. Valid but unresolved designs remain
   `needs_revision`; unresolved facts cannot become an approval.
4. Ask the same model for a separate critique of evidence support, requirements,
   conflicting constraints and missing facts. This is **not independent review**.
   Invalid or unavailable critique is discarded and the draft needs revision.
5. Recompute the five supported formulas in application code: rectangular area,
   box volume, DC power, idealized battery runtime and project effort. Model-written
   expressions are never executed. Positive part sizes, materials coverage,
   acceptance coverage and prerequisite graphs are checked locally.
   User-owned acceptance limits are recomputed too; failed or unresolved limits
   remain blocking regardless of model critique.
6. Render deterministic SVGs and readable HTML from validated data. Model text is
   escaped, with no executable HTML, scripts, tool calls or generated code execution.

The adapter retains loopback-only access, cloud-disabled checks, local model
verification, proxy bypass, redirect refusal, response size limits and cancellation.
Blueprint prompts request a conservative byte-based context budget, at least 16K
and at most 64K, leaving room for up to 8,192 output tokens. A model's advertised
context limit is checked when supplied. Long repairs may exceed the cap and fail
explicitly; reduce scope rather than assuming missing context was considered.
Model memory use and tokenizer overhead vary. No hardware performance is promised.

The index does not alter the library schema, write a cache to disk, or access notes.
It is closed after each search. Cancellation is checked throughout indexing and
ranking. The current bounds are 10,000 articles, 32 MiB of source-body UTF-8 text
and 50,000 passages. Exceeding a bound or encountering corrupt source text aborts
the search with an explicit error; it does not silently generate from a partial
library. Large corpora will need a persistent incremental index in a later change.

## Quality gates and current limits

Automated tests exercise all three makers through the real loopback HTTP adapter
with deterministic model fixtures, repair/truncation, citation errors, malformed
files, private-note exclusion, diagrams, exports, GUI workers, cancellation and
offline content installation. Fixtures test integration, not model intelligence.

No real Ollama model was installed in the implementation environment. Real-model
quality, latency, RAM/VRAM consumption, long-context behavior and engineering
correctness remain unverified. There is no state-of-the-art benchmark claim.

Run the repeatable three-case local-model evaluation after provisioning a model:

```bash
python tools/evaluate_blueprints.py --database fieldforge.db --model YOUR_LOCAL_MODEL --output evaluation-run-1
```

It records model, platform, elapsed time, structured-output success, repair count,
validation and exported artifacts. It does **not** invent a factual correctness
score. Before a release, have domain reviewers grade source support, dimensional
consistency, missing information, usability and failure handling across additional
shelter, water, power, construction, project and software cases. Include adversarial
source text, conflicting requirements, missing evidence and low-memory machines.

For retrieval alone, a repeatable 14-case regression suite runs without a model:

```bash
python -m tools.evaluate_blueprint_retrieval --database fieldforge.db --output retrieval-run
python -m tools.evaluate_blueprint_retrieval --database fieldforge.db --output retrieval-literal-run --literal
```

Run these from the source checkout with the bundled reference collection installed.
The evaluator compares a frozen pre-index baseline with the current retriever,
records exact excerpts, ranks, corpus/case fingerprints and elapsed times, and
refuses missing expected text or an existing output directory. Its labels are
small hand-authored regression targets, not an independent quality benchmark.
See [the measured results and limits](BLUEPRINT_RETRIEVAL_EVALUATION.md).

Next implementation gates:

- **Retrieval evaluation:** expand the implemented passage regression set with
  independent domain labels and multilingual cases; add hybrid semantic retrieval,
  reranking and a persistent incremental index. Keep lexical search available
  without an embedding model. Current retrieval can still miss synonyms; the
  no-FTS5 fallback also lacks stemming.
- **Engineering CAD:** dimension and tolerance constraints, joints, material/part
  catalogs, independently verified domain calculators and parametric CAD export.
  Gate STEP/DXF export on geometric validation and domain review; SVG envelopes
  are not a substitute for fabrication drawings or FEA.
- **Review/revisions:** independent human sign-off and provenance of every parameter;
  persistent project history and comparisons are implemented. Evaluate optional separate
  critic models without treating model agreement as proof.
- **Platform delivery:** packaged desktop installers and a mobile UI/runtime.
  These makers currently use Tk desktop and Python CLI; this change does not
  implement Android/iOS inference or certify macOS/Linux packaging.

Architecture: `fieldforge/blueprints/{schema,checks,acceptance,clearance,evidence,engine,engineering,geometry,geometry_report,render,projects,comparison,comparison_report}.py` contains the
headless design engine; `fieldforge/ui/{blueprints,blueprint_preview,blueprint_geometry,blueprint_history,blueprint_acceptance,blueprint_evidence}.py` contains
the desktop; `fieldforge/content` holds the reference pack. Existing knowledge,
backup, retrieval and local-assistant modules remain the shared foundation.

Upstream contracts: [Ollama structured outputs](https://github.com/ollama/ollama/blob/main/docs/capabilities/structured-outputs.mdx)
and [chat API](https://docs.ollama.com/api/chat). Schema conformance does not prove
that a factual claim or engineering design is correct.
