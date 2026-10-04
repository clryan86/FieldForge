# Ask Library — exact local sources before generated answers

This development slice adds an **Ask Library** desktop tab, a standalone window,
and a command-line question-to-reference tool. It does **not** install or run a
language model, generate answers, add more articles, or complete the planned
FieldForge offline AI system. Its value is inspectable retrieval from the text
already installed on the device.

## Using the new screen

Open **Ask Library**, enter a question, optionally choose a category, and select
**Find sources**. The example buttons use water storage, power budgeting, and
maintenance questions. Load the existing starter library in **Knowledge Library**
first if the database has no articles. A new import becomes searchable on the
next question without restarting the app; Refresh categories updates that menu.

Each result shows a `[S1]`-style label, matched and unmatched search words, a
source title, publisher, review-date field, and safety label. This is keyword
coverage, not a relevance probability, reliability score, or proof of an answer.
An empty search is not proof that a fact is absent from the library. Try other
wording or a different category, and examine the source yourself.

The excerpt is a contiguous, **exact slice of the locally stored article body**.
Open the full source to see that same captured version, its source URL, reuse
rights, body checksum, and surrounding context. Article body line numbers are
not page numbers or line numbers from the external publisher's original document.
The body hash detects changed text; it does not authenticate the publisher or
prove correctness. Metadata, including review dates, is supplied by article
authors. The interface does not endorse it as independently verified.

Source snapshots are retained in memory for the current report. A later article
update cannot silently alter a previously shown quote. Search again to get the
new version. Source URLs are displayed as attribution; they are **not fetched**
or opened by this feature. Content that looks like commands is displayed as text,
not executed or treated as instructions to an agent.

## What the retrieval actually does

1. Validate a nonempty question up to 512 characters and at most 24 distinct
   search words. Common English conversational filler is ignored. Numbers and
   negations remain; the original question is preserved. This is **not** semantic
   understanding of negation, intent, safety, or meaning.
2. Use parameter-bound, literal-word FTS5 queries over article titles and bodies.
   A question can return partial word matches rather than requiring its entire
   conversational phrasing. Category filtering is exact, not an inferred topic.
3. Read candidates and source text in one SQLite read transaction. Inspect up to
   64 candidates and up to 16 MiB of candidate body data. Exact word coverage,
   title matches, and best-paragraph coverage determine a deterministic ranking.
   Descriptive titles get extra weight so an orientation page mentioning many
   topics need not outrank a dedicated reference.
4. Validate article metadata and its stored body checksum. Skip invalid candidates
   with a visible warning rather than citing text whose checksum failed.
5. Select a matching paragraph, preferring substantive text over recognized
   SOURCE/REFERENCES/ORIGIN/BIBLIOGRAPHY paragraphs. Include neighboring complete
   paragraphs when they fit a 2,400-character excerpt. If the matching paragraph
   is too long, **do not clip it into an apparent complete instruction**: offer
   the full source without fabricating an excerpt. A title-only match is labeled
   as such and does not pretend to be quoted body evidence.

The top 5 results are shown by default (CLI can request 1–8). Candidate/byte caps
are reported as partial-search limitations. The usual query time budget is five
seconds. Cancellation and timeout checks are cooperative, not a hard real-time
guarantee: an ongoing SQLite operation or large Unicode normalization can finish
before the next check.

Without an available/current FTS index, the feature uses a literal whole-word
fallback and says so. It may scan many rows, be slower, and produce a different
candidate ordering. It does not rebuild or modify an index during a question.
Database errors are not disguised as empty results. Only FTS unavailability is
handled as a portability fallback.

Normalization uses Unicode case folding and accent decomposition. There is no
stemming, synonym dictionary, translation, embedding search, contradiction
resolution, or guarantee that every relevant passage is found. SQLite and Python
Unicode token rules can differ. A word inside a URL embedded in an article body
can still be a word match. These limitations are why results are always labeled
**source excerpts, not an AI-generated answer**. Even matching every word does
not mean a source answers the question.

## High-stakes use

Excerpts can omit conditions elsewhere in a source. Medical, water-safety,
equipment, and other high-stakes labels trigger an additional caution when
present. This is not a comprehensive hazard classifier; imported labels may be
missing or wrong. Search results are not diagnoses, treatment recommendations,
construction instructions, or a safety clearance. Full context and qualified
review remain necessary. Existing starter articles remain explicitly AI-drafted
and not independently specialist-reviewed; this feature does not change that.

## Privacy and lifecycle

Search reads article titles and bodies. It does not query the separate household,
article-annotation, or pathway-progress tables, and does not save a question log.
Private information placed inside an article body is nevertheless searchable.
No question or article is sent to a cloud API or even a localhost server. There
are no model downloads, network clients, account requirements, or new dependencies.

Copy question + source report is an explicit user action and puts the question
and cited excerpts on the **system clipboard**. Protect that clipboard; clearing
the view does not clear prior clipboard contents, saved terminal output, or open
source windows. CLI arguments may remain in shell history. This is not encrypted
storage or guaranteed memory erasure. The underlying FieldForge database and
article packs retain their existing privacy characteristics.

The graphical search runs on a worker so the main event loop stays responsive.
Only the main thread touches Tk. Cancel, Clear, or destroying the panel signals
cancellation and invalidates the request token so late results cannot reappear.
An in-progress lookup does not mutate user data, so closing this panel does not
need a restore/save confirmation. Existing article and learning-note save guards
in the main application remain in place.

## Commands and updating

From an updated source checkout:

```sh
python -m fieldforge.knowledge.assistant "How do I calculate a power budget?" --database ./playground.db
python -m fieldforge.knowledge.assistant "measurement" --database ./playground.db --json
python -m fieldforge.ui.assistant
```

The CLI requires an already initialized library database and reads it without
creating or migrating it. Open the updated application first when a schema needs
initializing. The standalone UI uses `FIELDFORGE_DB` or the usual
`~/.fieldforge/fieldforge.db`; the existing Windows source launcher selects the
playground path when no override is set. `py` can replace `python` on Windows.

The new tab requires updated **application code**, not another JSON content pack.
An already-downloaded ZIP does not update automatically. Close the old application
and back up the database before changing builds. No merge, signed installer,
mobile package, or release is implied by this development branch.

## Verification scope

Targeted unit and real Tk tests cover FTS/fallback operation, natural questions,
source ordering, original Unicode/line offsets, untrimmed conditions, long
paragraph handling, partial matches, source snapshots after updates, private
record exclusion, corruption notices, query safety, caps, cancellation, timeout,
CLI output, read-only behavior, clipboard actions, late-result rejection, worker
thread separation, and notebook integration. GUI tests require a display and
skip when it is unavailable. Full-checkout integration tests use the actual
starter articles, household model, and pathway notes.

Technical documentation consulted for this implementation:
- SQLite FTS5, column filters and BM25: https://www.sqlite.org/fts5.html
- Python sqlite3, read-only URIs, progress handlers and connection closure: https://docs.python.org/3/library/sqlite3.html
- Python Tkinter threading/event-loop model: https://docs.python.org/3/library/tkinter.html

No new third-party domain reference text is reproduced by this change. A future
local-model adapter will need separate model/runtime packaging, hardware tests,
context isolation, source-grounding evaluation, and high-stakes safety review.
None of those are claimed complete here.
