# Education Foundations: offline teaching and practice

This collection supplies **88 complete lesson drafts** in the `education` category,
bringing that category to 100 articles and the full library to 355. Each lesson
includes an audience, prerequisites, learning goal, materials, explanation and
worked examples, three practice prompts, answers or assessment guidance, and
adaptations: **264 practice prompts with corresponding answers or assessment
guidance**. The text works without network access or a local AI model.

These are original AI-assisted FieldForge drafts, **not an independently reviewed
or accredited curriculum**. The first edition is in English. Its phonics examples
are specifically for English; they must not be transferred unchanged to another
writing system. Adult adaptations are suggestions, not evidence that school-age
research automatically generalizes to adults.

## Learning paths

Browse the **education** category and look for titles beginning `Education 01:`
through `Education 88:`. Prerequisites identify skills to check; they do not require
every learner to repeat a lesson they already understand.

| Path | Lessons | Content |
| --- | --- | --- |
| Teaching | 01–04 | Start a learning group; plan a worked-example lesson; spaced practice; useful assessment and feedback |
| Literacy | 05–10 | English sound-letter relationships; decoding and spelling; short sentences; vocabulary and comprehension; writing; notices and instructions |
| Numeracy | 11–16 | Counting; place value; addition/subtraction; multiplication/division; fractions; decimals and percentages |
| Applied numeracy | 17–21 | Metric measurement; perimeter/area; time; tables/graphs; ratios and scaling |
| Inquiry and transfer | 22–24 | Observation and fair comparisons; source evaluation; teaching a practical skill and keeping a record |
| Further reading skills | 25–30 | More letter sounds and short vowels; blends; digraphs; silent-e; word endings; connected reading with an explicit word preview |
| Further writing | 31–33 | Paragraph focus and details; narratives; explanations with evidence and limits |
| Further mathematics | 34–37 | Unlike-fraction addition/subtraction; fraction multiplication/division; signed integers; simple equations |
| Science and geography | 38–40 | States of matter; interpreting seed-germination observations; map legends, grids and scale |
| Longer-word reading | 41–43 | Vowel teams; vowel-plus-r spellings and accent variation; syllables, prefixes and suffixes |
| Practical literacy | 44–46 | Required and optional form fields; feasible schedules; conditional instructions and conflicting revisions |
| Arithmetic and data | 47–52 | Rounding and estimation; partial products; larger division and remainders; proportional tables; mean, median and range; probability and observed frequency |
| Further inquiry | 53–56 | Forces and motion; water-cycle pathways; historical sources and timelines; shared decisions and accurate records |
| Reading and summarizing | 57–60 | More vowel teams and diphthongs; prepared connected reading and phrasing; accurate informational summaries |
| Decimal arithmetic and percent | 61–64 | Decimal addition/subtraction, multiplication and division; percent, part and whole; percentage points and relative change |
| Geometry | 65–68 | Angles and line relationships; triangle angles and area; circle circumference and area; rectangular-prism volume and cubic units |
| Everyday science | 69–72 | Light-ray models and shadows; vibration, pitch and loudness; food-web arrows; weather records and limits on climate conclusions |
| Spelling and sentences | 73–76 | Suffix spelling changes; apostrophes and contractions; subject/verb and pronoun clarity; clauses and sentence connections |
| Practical reading and writing | 77–80 | Requests and confirmation; inventory discrepancy notes; a longer narrative with evidence-based inference; comparison paragraphs |
| Mathematical reasoning | 81–86 | Operation order; multi-step word problems; coordinate points; rules, tables and lines; translations/reflections; factors and multiples |
| Data literacy | 87–88 | Neutral survey questions, sampling limits and nonresponse; chart baselines, scale and rate comparisons |

For a first session, a facilitator can read lesson 01, then choose a literacy or
numeracy entry point with the learner. Lessons 05–07 introduce only a small initial
English phonics sequence; lessons 25–30, 41–43, 57–59 and 73 extend it. The extension
is designed for multiple sessions and still does not cover a full systematic reading curriculum.
It includes new-word previews rather than assuming every passage is independently
decodable for every learner. Lesson 08's richer passage is an explicit read-aloud option
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

All 267 archived article records and the first 72 education lesson records are
preserved exactly. Importing the full 88-lesson pack adds 16 lessons to a
72-lesson installation, 32 to a 56-lesson installation, 48 to a 40-lesson
installation, or 64 to the original 24-lesson edition, without `--replace`.
Earlier records are unchanged, and existing notes and bookmarks remain attached
to their slugs.
The lessons use the reserved `fieldforge-education-01` through
`fieldforge-education-88` slugs, so they
do not duplicate or rename the existing archived education references.

## Sources and rights

The editable source is `fieldforge/content/education/lessons.json`. Its reference
inventory records titles, publishers, URLs, access dates and the scope of each
reference. References consulted for this edition include the IES/WWC practice
guides on foundational reading, reading comprehension, elementary writing, early
mathematics, and study methods, plus relevant OpenStax *Prealgebra 2e* sections.
The second set also points to the University of Florida Literacy Institute's
phonics resources, University of Minnesota Extension's seed-starting information,
NASA Glenn's states-of-matter reference, and USGS map-symbol resources. It is not
a reproduction or implementation of those publishers' complete curricula.
Lessons 41–56 add scoped references for division, statistics and probability,
NASA's motion overview, USGS's water-cycle overview and the Library of Congress's
introduction to primary-source inquiry. Historical records, forms, schedules
and group decisions in this batch are explicitly fictional practice scenarios.
Lessons 57–72 add references for decimal arithmetic, percent applications,
geometry, light and sound, plus NOAA resources on food webs and weather/climate.
Their passages, calculations, pond model and temperature records are original
teaching examples, not copied source exercises or observations of a real site.
Lessons 73–88 add scoped references for suffix spelling, edited-English
conventions, operation order, coordinates, factors, sampling and chart scales.
They point to UFLI, Purdue OWL, OpenStax, Minnesota STEM Teacher Center and
the UK Government Analysis Function. Requests, records, narratives, surveys
and chart data remain original fictional practice examples.

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

The source's default edition remains `2026-10-02` for lessons 01–24. Lessons 25–88
carry an explicit `2026-10-03` edition. The compiler honors a per-lesson edition so
adding a later batch does not rewrite the provenance or body hashes of earlier
lessons. Changing an already-imported lesson's text still creates a deliberate
content conflict under the normal importer; this edition mechanism does not
silently replace a user's content.

Automated checks cover exact source/pack correspondence, original-record
preservation, prerequisite order, answer coverage, hashes, deterministic rebuilds,
offline installation/search, upgrades from the archived corpus and all four earlier
education editions (24, 40, 56 and 72 lessons), private-note preservation and conflict rollback.
They cannot establish pedagogical effectiveness. Before treating this as reviewed
material, educators should check factual explanations and answer keys, try the
activities with appropriate learners, assess accessibility and language needs,
and record the review's scope. Current `reviewed_on` values remain empty.

Follow-on content priorities: add more reading passages at explicitly supported
decoding levels, strengthen revision and vocabulary practice, extend algebra
and data reasoning, and develop more science and vocational learning activities.
Multilingual editions require suitable local expertise. Independent educator
review remains a gate before any claim of reviewed instructional quality.
