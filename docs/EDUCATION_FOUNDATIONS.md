# Education Foundations: first offline teaching pack

This addition supplies **24 complete lesson drafts** in the `education` category,
bringing that category to 36 articles and the full library to 291. Each lesson
includes an audience, prerequisites, learning goal, materials, explanation and
worked examples, three practice prompts, answers or assessment guidance, and
adaptations. The text works without network access or a local AI model.

These are original AI-assisted FieldForge drafts, **not an independently reviewed
or accredited curriculum**. The first edition is in English. Its phonics examples
are specifically for English; they must not be transferred unchanged to another
writing system. Adult adaptations are suggestions, not evidence that school-age
research automatically generalizes to adults.

## Learning paths

Browse the **education** category and look for titles beginning `Education 01:`
through `Education 24:`. Prerequisites identify skills to check; they do not require
every learner to repeat a lesson they already understand.

| Path | Lessons | Content |
| --- | --- | --- |
| Teaching | 01–04 | Start a learning group; plan a worked-example lesson; spaced practice; useful assessment and feedback |
| Literacy | 05–10 | English sound-letter relationships; decoding and spelling; short sentences; vocabulary and comprehension; writing; notices and instructions |
| Numeracy | 11–16 | Counting; place value; addition/subtraction; multiplication/division; fractions; decimals and percentages |
| Applied numeracy | 17–21 | Metric measurement; perimeter/area; time; tables/graphs; ratios and scaling |
| Inquiry and transfer | 22–24 | Observation and fair comparisons; source evaluation; teaching a practical skill and keeping a record |

For a first session, a facilitator can read lesson 01, then choose a literacy or
numeracy entry point with the learner. Lessons 05–07 introduce only a small initial
English phonics sequence. They need a broader systematic sequence to develop full
reading proficiency. Lesson 08's richer passage is an explicit read-aloud option
until the learner knows its additional spelling patterns. No completion timetable,
grade equivalence or standardized assessment score is claimed.

## Install and browse

New installations receive the lessons through the ordinary bundled library install:

```bash
python -m fieldforge.blueprints --database fieldforge.db install-library
python -m fieldforge.knowledge --database fieldforge.db list --category education
```

For an existing FieldForge installation, import just the new content using its
normal knowledge-pack importer:

```bash
python -m fieldforge.knowledge --database fieldforge.db import fieldforge/content/packs/education-foundations.json
```

The desktop Knowledge Library also accepts this JSON pack through **Import pack**.
No personal annotations are included. Repeated imports of identical content are
idempotent. A conflicting local article aborts the entire import; it is not silently
replaced. Do not use `--replace` unless you intend to overwrite your local version.

All 267 existing article records are preserved exactly. The new lessons use the
reserved `fieldforge-education-01` through `fieldforge-education-24` slugs, so they
do not duplicate or rename the existing archived education references.

## Sources and rights

The editable source is `fieldforge/content/education/lessons.json`. Its reference
inventory records titles, publishers, URLs, access dates and the scope of each
reference. References consulted for this edition include the IES/WWC practice
guides on foundational reading, reading comprehension, elementary writing, early
mathematics, and study methods, plus relevant OpenStax *Prealgebra 2e* sections.

Activities, fictional passages, examples and answer keys are original drafts.
No third-party textbook text or images are reproduced. External references provide
background, not an endorsement or a claim that these lessons were tested. They
retain their own rights and are not downloaded at runtime. Article metadata names
FieldForge as the draft publisher; the body identifies its background references.

The original lesson text is offered under CC BY-SA 4.0. Retain attribution, draft
status and the license notice when adapting or distributing it. This does not
change the licensing of application code or external references.

## Maintain and review

Edit the source JSON, then run from the repository root:

```bash
python -m tools.build_education_library
pytest tests/test_reference_library.py tests/test_education_library.py
```

The offline compiler produces the education-only pack, updates the existing
combined reference pack and its catalog, and leaves other article records intact.
The combined pack still installs in one database transaction. A Wikibooks refresh
must be followed by this compiler to restore the education addition.

Automated checks cover exact source/pack correspondence, original-record
preservation, prerequisite order, answer coverage, hashes, deterministic rebuilds,
offline installation/search, private-note preservation and conflict rollback.
They cannot establish pedagogical effectiveness. Before treating this as reviewed
material, educators should check factual explanations and answer keys, try the
activities with appropriate learners, assess accessibility and language needs,
and record the review's scope. Current `reviewed_on` values remain empty.

Follow-on content priorities: extend the phonics sequence, add richer leveled
reading, expand writing genres, provide adult-focused literacy sequences, include
multilingual editions with suitable local expertise, and develop further science,
history, civic and vocational learning paths. These are future additions, not
features claimed for this first pack.
