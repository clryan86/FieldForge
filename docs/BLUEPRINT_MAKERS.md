# Three offline blueprint makers

The library now includes a bundled reference collection and three distinct design
workflows. Open **Knowledge Library → Blueprint Makers**, or run
`fieldforge-blueprints --database fieldforge.db gui`.

| Maker | Inputs | Outputs and local checks |
| --- | --- | --- |
| Engineering | Brief, dimensions, constraints, available materials/tools, evidence keywords | Dimensioned top/front/side envelope drawings; materials linked to part IDs; ordered build steps; explicit assumptions; fixed-formula calculations with exact units; risks and requirement acceptance checks |
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
2. Load installed models and select one. Optional evidence keywords help narrow
   lexical retrieval. Private library notes are never included.
3. Generate. The status shows retrieval, design, repair when needed, and critique.
4. Inspect **Blueprint and checks**, the source excerpts, and **Drawings**. The text
   view provides an accessible equivalent to diagrams. Keyboard arrows and Page
   Up/Down scroll the drawing canvas.
5. Edit the canonical JSON in **Edit design**, then **Apply edits and recompute**.
   Edits invalidate the earlier model critique. Unapplied edits cannot silently
   disappear into a save/export of the old version.
6. Save a `.json` design or export a new directory containing `report.html`,
   `blueprint.json`, SVG drawings and a README. Reports print from a browser and
   work entirely offline, with no scripts, fonts, images or assets fetched remotely.

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
```

`python -m fieldforge.blueprints` is equivalent. Options include `--constraints`,
`--resources`, `--evidence-query`, `--port` and `--timeout` (maximum 300 seconds per
model call). A run makes two model calls, or three when repair is needed. Cancellation
closes FieldForge's request; Ollama may take additional time to release its GPU.

## Generation and validation pipeline

1. Retrieve up to eight matching, checksum-checked local excerpts, at most 1,200
   characters each. Retrieval reuses the existing FTS/literal search and preserves
   article offsets, attribution, license, review status and source checksum.
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
6. Render deterministic SVGs and readable HTML from validated data. Model text is
   escaped, with no executable HTML, scripts, tool calls or generated code execution.

The adapter retains loopback-only access, cloud-disabled checks, local model
verification, proxy bypass, redirect refusal, response size limits and cancellation.
Blueprint prompts request a conservative byte-based context budget, at least 16K
and at most 64K, leaving room for up to 8,192 output tokens. A model's advertised
context limit is checked when supplied. Long repairs may exceed the cap and fail
explicitly; reduce scope rather than assuming missing context was considered.
Model memory use and tokenizer overhead vary. No hardware performance is promised.

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

Next implementation gates:

- **Retrieval evaluation:** curated queries with expected passages, hybrid semantic
  retrieval/reranking, source diversity and coverage metrics; keep literal search
  available without an embedding model. Current retrieval can miss synonyms.
- **Engineering CAD:** dimension and tolerance constraints, joints, material/part
  catalogs, independently verified domain calculators and parametric CAD export.
  Gate STEP/DXF export on geometric validation and domain review; SVG envelopes
  are not a substitute for fabrication drawings or FEA.
- **Review/revisions:** persistent project history, change comparison, independent
  human sign-off and provenance of every parameter; evaluate optional separate
  critic models without treating model agreement as proof.
- **Platform delivery:** packaged desktop installers and a mobile UI/runtime.
  These makers currently use Tk desktop and Python CLI; this change does not
  implement Android/iOS inference or certify macOS/Linux packaging.

Architecture: `fieldforge/blueprints/{schema,checks,engine,render}.py` contains the
headless design engine; `fieldforge/ui/{blueprints,blueprint_preview}.py` contains
the desktop; `fieldforge/content` holds the reference pack. Existing knowledge,
backup, retrieval and local-assistant modules remain the shared foundation.

Upstream contracts: [Ollama structured outputs](https://github.com/ollama/ollama/blob/main/docs/capabilities/structured-outputs.mdx)
and [chat API](https://docs.ollama.com/api/chat). Schema conformance does not prove
that a factual claim or engineering design is correct.
