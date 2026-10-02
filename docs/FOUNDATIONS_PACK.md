# Foundations learning pack: real lessons, not topic placeholders

This collection adds **20 original lessons and 40 numeric self-check exercises**
on mathematics, measurement, planning arithmetic and useful records. There are
more than 7,800 words of core teaching text, before objectives, exercises,
worked answers, attribution and repeated limits. It is a focused introductory
collection, not a complete mathematics textbook, civilization-rebuilding course,
medical corpus, engineering design manual or independently reviewed curriculum.
All examples use fictional, harmless paper/classroom scenarios.

## Use the updated desktop

Choose **Knowledge Library → Foundations Pack…**. The bundled lessons can be read
and practiced immediately, even before installing their articles in the database.
The suggested order and explicit prerequisites explain which earlier lessons are
useful; there is no locked content or automatically inferred competence.

The **Read bundled lesson** tab always shows the bundled edition. It is not a
preview of a modified article already in your library. The state beside each
lesson distinguishes Not installed, Installed — same edition, and Different /
unreadable — preserved. This comparison checks the actual article body and
metadata against this bundled edition; it does not authenticate a publisher.

The **Practice & check** tab accepts an exact integer, decimal or fraction such
as `12`, `0.5` or `1/2`. It compares rational values, so `2/4` and `0.5` are equal.
It does not treat a rounded decimal such as `0.33333333` as exactly `1/3`. Prompts
state the answer unit; enter the number without a unit or percent sign. Input is
bounded and does not accept executable expressions, exponent notation, commas,
NaN, infinity or zero denominators. Wrong/invalid responses stay editable.
**Show worked answer** gives the explanation rather than just an answer key.
Changing a lesson, question or response clears stale feedback.

No responses, score history, learner names, completion badges or grades are
stored. A matching answer only checks this exercise's arithmetic under its
stated assumptions; it does not update Pathways practice or prove competence.
Closing the window loses the current response. Paper practice and teach-back
remain separate learning activities, not automatically graded events.

Acknowledge the original/unreviewed-material notice and choose **Add missing
lessons to Library** to make all absent lessons searchable. The entire operation
runs in one database transaction. Existing identical lessons are recognized;
existing different or damaged rows are kept, not overwritten or silently
'repaired'. The report identifies the counts in each group and the list marks
individual preserved records. You can inspect your existing copy in the normal
Library. Installation never changes private annotations, personal reading links,
practice records or unrelated articles. It does not remove the twelve starters.
With all starters and no additional/conflicting records, the library has 32
articles after this pack is installed.

The installer rechecks under the transaction's writer lock, not against a stale
preview. Concurrent installs therefore cannot silently overwrite each other. A
write failure rolls back all new article insertions, including search-index
updates. Expected conflicts are *preserved and skipped*, not transaction errors.
Normal closing is blocked during installation; closing a read-only inspection
can discard its late result without writing articles. The existing Library
note-save and busy/close guards are used when opening the pack window.

## What is covered

01. Counts, packages, contents and explicit units
02. Place value, arithmetic order, inverse checks and remainders
03. Fractions, decimals and equal parts
04. Ratios, proportional scaling and fixed versus variable work
05. Percentages, reserves, changing bases and percentage points
06. Metric length conversions and stated inch/foot factors
07. Perimeter, area, simple shape formulas and layout limits
08. Geometric volume, capacity and cubic-unit conversions
09. Repeat measurements, simple stipulated bounds and uncertainty limits
10. Drawing scale and explicitly defined local paper coordinates
11. Elapsed time, rates and serial/parallel work assumptions
12. Receipts, issues, transfers and reconciled stock ledgers
13. Stock-duration scenarios without implied rationing advice
14. Paper energy budgets: watts, watt-hours and usable-output assumptions
15. Rearranging formulas and checking dimensions
16. Tables, graphs, cumulative totals and honest missing-data handling
17. Mean, median, range and differently sized groups
18. Harmless comparisons, confounding and observation versus causation
19. Reproducible technical records, revisions and privacy
20. An integrated paper-workshop planning and teach-back capstone

Every lesson includes an objective, recommended earlier lessons, substantial
explanation, a worked scenario, two practice questions and their worked answers.
Optional Pathways goal IDs are suggestions in the text. Use the existing
**Manage reading links** workflow to make personal associations; this installer
does not create them on your behalf or change the prerequisite map. Linked
readings remain subject to the existing changed-source warnings.

## Offline distribution and backwards compatibility

All lesson text is part of the Python package, not fetched from source links or
stored only in a repository-level data folder. No new application dependency,
database schema or knowledge-pack format is added. CI verifies export from the
built wheel away from the source tree, in addition to the source tests.

A compatible JSON knowledge pack can be generated from bundled text alone:

```sh
python -m fieldforge.knowledge.foundations export Foundations-v1.json
```

This creates a **new** JSON file and refuses existing destinations. It never
exports the user's database or annotations. An older FieldForge build with the
existing **Import Pack** feature can import the articles, including worked
answers, without new Python dependencies. Keep **Allow replacing conflicts**
off to preserve existing content. The older generic pack importer rejects a
conflicting pack rather than using the new installer's preserve-and-skip policy.
Importing JSON installs content, not the new lesson-browser/self-check interface.

The explicit command-line installation form is:

```sh
python -m fieldforge.knowledge.foundations install --database my-library.db --acknowledge-unreviewed
```

On Windows `py -3` may replace `python`. Use the database actually opened by your
app; a separate path creates/uses a separate library. Nothing is installed by
merely importing the module or reading the pack's preview.

After installation, articles work with existing Library search, Ask Library
source retrieval, Field Binder and Pocket Reader. Portable HTML retains full
lesson bodies, questions and worked answers. Its search is interactive, but the
new numerical self-check widget belongs to the desktop lesson window, not that
HTML. Original private notes remain excluded according to each export mode's
existing settings. A content-only pack and a read-only HTML collection are not
full database backups. Complete SQLite snapshots include installed articles and
separately stored notes, as before.

## Review, rights and safety scope

This is original AI-drafted FieldForge content, not copied textbook chapters.
Independent specialist review has **not** been performed; all article review
dates remain empty. Software tests check the forty numeric answers independently
using exact arithmetic, not the full pedagogical quality or real-world adequacy
of every sentence. The source-publisher field says FieldForge, not NIST.

Related NIST links support the identified SI unit conventions and are labeled
as references, not endorsements. The complete linked publications are not
bundled or downloaded. References consulted on 2026-10-01:

- NIST Metric (SI) Prefixes: https://www.nist.gov/pml/owm/metric-si-prefixes
- NIST conversion factors, Appendix B.8: https://www.nist.gov/pml/special-publication-811/nist-guide-si-appendix-b-conversion-factors/nist-guide-si-appendix-b8
- NIST SI Units — Volume: https://www.nist.gov/pml/owm/si-units-volume
- NIST SP 330, Section 2 (derived units): https://www.nist.gov/pml/special-publication-330/sp-330-section-2

The original-text rights field retains the project's existing position: a
redistribution license has not been selected. This milestone does not license
third-party publications, choose a new project license or import copyrighted
manuals. Sources keep their own terms. No claim of medical, nutritional,
construction, electrical, surveying, food-treatment or repair competence is
made by the exercises. Reserve factors and equipment figures are stipulated
fictional inputs, not recommendations for the user's household.

## Verification boundaries

Tests cover every numerical exercise, unit/fraction input bounds, content and
prerequisite structure, FTS/literal search, read-only preview, no-op and concurrent
installations, edited/corrupt-row preservation, rollback, private-note separation,
compatible pack export/import, actual Tk reading/practice/consent/worker/close
flows, existing Pathways links, Ask Library, full recovery and portable outputs.
The full existing suite is also run because the shared Library toolbar changes.

Source/browser CI results must be checked for the exact commit before declaring
a new downloadable development ZIP tested. Hosted Windows and desktop browser
checks are not physical Android/iOS or printer certification. Pocket Reader keeps
its documented device/file-opening limitations. Close the old app and back up
its database before updating source; downloaded copies do not update themselves.
