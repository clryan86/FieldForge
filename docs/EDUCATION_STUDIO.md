# Education workspace

Open **Education** beside Blueprints, or use **Go to section → Education** in a
compact window. It works immediately with bundled content, even in an existing
database where the reference library has not been installed.

The default **Guided: Measure & plan** course contains five original lessons:

1. Fractions: equal parts, equivalent amounts and a fraction of a length.
2. Length: nonzero ruler starts, metric units and reverse checks.
3. Area and perimeter: boundary versus surface and consistent units.
4. Scale drawings: object versus drawing dimensions and area scaling.
5. Paper panel plan: combine the preceding ideas and review an incomplete claim.

Each maths lesson includes a diagram with a text description, worked reasoning, four numeric
exercises and one explanation task. These are paper exercises; they are not
construction specifications. The existing 172 Education Foundations lessons
are also available by track or through **All lessons**. Their article text and
library notes are preserved. These reference lessons use written self-review;
they have not all been rewritten into the guided course format.

Choose **Guided: Read & write** in the course/track selector for five further lessons:

1. Read a notice: details, conditional requests, changed information and gaps.
2. Trace events: sequence, stated causes, evidence and limited inferences.
3. Summarize a report: central point, relevant evidence and limits.
4. Revise instructions: named objects, action order and completion checks.
5. Revise a request: purpose, quantity, timing, uncertainty and a useful reply.

These contain original fictional passages, worked before/after revisions,
15 choice questions and 10 writing tasks. The passages are supported reading,
not a beginner phonics sequence or an independently established reading level.
The **Passage / model** tab stays available while you write; **Question & options**
shows the current prompt and complete option text. Select A, B or C, then use
**Check choice** for feedback about that option's relationship to the source.
The explanation field remains self-reviewed. Writing prompts include comparison
criteria and example responses, allowing more than one valid wording.

## Practice workflow

**Guided: Investigate & reason** connects measurement and literacy in four lessons:

1. Measurements: mean, range, consistency, reference checks and unusual readings.
2. Fair comparisons: competing explanations, order effects and a follow-up plan.
3. Samples: counts versus rates, percentage points, self-selection and missing users.
4. Evidence report: combine data, method, missing records and a qualified conclusion.

The 24 exercises include eight exact numeric checks, eight choice checks with
feedback for each distractor, and eight written tasks with comparison criteria.
Each lesson supplies a fictional dataset, worked reasoning and a labeled chart
with a zero baseline and a text description. Charts also appear in exported
worksheets. **Passage / model** holds the data record while you answer. The final
report asks for a method, calculated result, limitations and a specific next step;
it is self-reviewed, not automatically graded. The datasets illustrate reasoning
and do not establish real product performance, causal effects or teaching outcomes.

The course uses [NGSS Appendix F](https://www.nextgenscience.org/sites/default/files/resource/files/Appendix%20F%20%20Science%20and%20Engineering%20Practices%20in%20the%20NGSS%20-%20FINAL%20060513.pdf)
and [NIST measurement terminology](https://www.nist.gov/pml/nist-technical-note-1297/nist-tn-1297-appendix-d1-terminology)
as background. It is not a validated standards-aligned curriculum or a complete
measurement-uncertainty course. All datasets, prompts and worked examples are original.

Read the goal and worked examples, then select **Practice & explain**. Write an
answer and explain your method. **Check number** accepts exact integers, decimals
or fractions in the displayed unit, without units typed into the number field.
For example, `3/8` and `0.375` match, while `0.38` does not. Matching a numeric value
does not verify the explanation or a requested simplified form.

Wrong answers that match an authored common mistake receive a specific prompt.
Other wrong answers get a units/representation check. **One hint** reveals the
next hint without exposing every hint at once. **Show worked answer** provides
reasoning or comparison criteria. The two reflection buttons record your own
judgment after comparing; they never assign an automatic prose grade.

Drafts save after a short typing pause, on question/lesson changes, before full
backup, and on normal desktop close. Check the status line for save failures.
The UI retains unsaved text and blocks navigation/close when a write fails.
**Export worksheet** can preserve that text even when the database write fails.
It creates a new HTML file and will not overwrite an existing file. The answer
key is collapsed; open it before printing if answers should appear on paper.
Use **Resume saved practice** to return to the most recently saved question.
If another window changed a response, export your draft and use **Reload saved
answer** to load the current record; discarding a different draft requires confirmation.

One database holds one practice record per question, not separate learner
profiles. Exported worksheets and database backups contain personal responses.
Hints/reveals remain recorded on that question; editing an answer clears its
current check and self-review but preserves the support history. The app cannot
detect other help used, and it does not infer independent mastery.

## Content and storage boundaries

The fourteen guided lessons add 74 exercises to the original 516 reference prompts.
They are AI-assisted teaching drafts, not independently educator-reviewed or
validated with learner outcomes. Instructional design background is the
[IES study guide](https://ies.ed.gov/ncee/wwc/PracticeGuide/1); this does not mean
that IES evaluated or endorsed FieldForge. The original examples, answer keys,
common-mistake feedback and diagrams are CC BY-SA 4.0.

The literacy course also draws on the IES guides for
[K–3 comprehension](https://ies.ed.gov/ncee/wwc/PracticeGuide/14) and
[elementary writing](https://ies.ed.gov/ncee/wwc/PracticeGuide/17) as instructional
background. The original passages and activities are not those guides' tested
interventions, and adaptations for older learners have not been validated.

Private responses use the `education_work_v1` table in the active SQLite database.
Full database snapshots preserve this table; article-only exports do not.
Question content fingerprints keep revised prompts from inheriting stale check
results. Existing versions of work remain in the database. Concurrent saves use
revision checks, so another open window cannot silently replace an older draft.
The literacy extension preserves all 541 previously shipped question fingerprints.
The evidence course additionally preserves all 566 fingerprints shipped before it.
New questions include source passages and choices in their fingerprints, so
changed evidence or options cannot inherit a previous question's check result.

Automated checks cover exact arithmetic, misconception feedback, draft edits,
self-review, concurrent writes, real backup/restore, HTML escaping, UI navigation,
minimum-window controls and the normal desktop entry point. The packaged Windows
self-test repeats an actual attempt/hint/save/restore/export workflow using
temporary records. These software checks are not teaching-effectiveness evidence.
