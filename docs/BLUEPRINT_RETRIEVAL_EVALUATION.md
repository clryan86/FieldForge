# Blueprint passage retrieval regression results

The passage retriever found all 13 labeled passages in the top eight results of
this **small, hand-authored regression set**, compared with 10 for the previous
retriever. This is evidence of improvement on these cases, not a state-of-the-art
benchmark claim, factual validation, or proof that designs are safe or complete.

## Setup and reproducibility

These recorded results use the pre-education-expansion corpus below. The current
bundle also contains 72 Education Foundations drafts; rerunning with it produces
a different corpus fingerprint. These historical scores are not measurements of
that expanded corpus.

- Run date: 2026-10-02, Windows 11, Python 3.12.14.
- Corpus: the 267-article bundled reference pack, installed into a fresh database.
- Corpus fingerprint (sorted slug/body-checksum pairs):
  `fe3d2a0124a85a579abc8c10194e342ab0bb81bbb6ac11a68f1a76518c305944`.
- Case file SHA-256:
  `f7702f2817808792b6c022b97f17f914925afd9b691705521b11463f16d4879d`.
- `tools/blueprint_retrieval_cases.json`: 12 positive requests covering engineering,
  project planning and software, with 13 expected passage markers; two empty-result
  requests. The multi-passage rain-barrel case expects two sections from one article.
- `tools/evaluate_blueprint_retrieval.py` includes the frozen pre-index retrieval
  function from commit `52ff3e3` as its baseline. The baseline uses the library's
  FTS path when available; `--literal` selects the candidate's no-FTS5 path only.
- No LLM, embedding model, external reranker or network was used.

Run from the checkout after installing the reference pack:

```bash
python -m tools.evaluate_blueprint_retrieval --database fieldforge.db --output retrieval-run
python -m tools.evaluate_blueprint_retrieval --database fieldforge.db --output retrieval-literal-run --literal
```

The new output directory contains the complete per-case report, returned source
excerpts, expected markers, ranks, diagnostics and fingerprints. Missing expected
text aborts evaluation. Source text retains the article attribution and CC BY-SA
license; labels identify retrieval targets, not endorsement of their claims.

## Observed results

| Measurement | Previous article retrieval | Passage FTS5 | Passage literal fallback |
| --- | ---: | ---: | ---: |
| Expected passage markers found in top 8 | 10 / 13 | 13 / 13 | 12 / 13 |
| Passage recall at 8 | 76.9% | 100% | 92.3% |
| Mean reciprocal rank of first expected passage, positive cases | 0.792 | 1.000 | 0.917 |
| Correctly empty results | 1 / 2 | 2 / 2 | 2 / 2 |
| Total retrieval time over 14 cases, one local run | 3.30 s | 1.91 s | 5.69 s |

The previous retriever missed the fittings section when another section of the
rain-barrel article had already been selected, the journaling passage for crash
recovery, and the circular-wait prevention passage. The new FTS5 path found these
targets. Its literal fallback still missed the circular-wait target; word forms
and passage selection remain relevant limits. Empty-result cases exercise an
unknown token and a content-free request, not general out-of-domain detection.

Times include constructing the disposable index and are a single local measurement,
not hardware promises or a controlled latency study. No relevance precision score
is reported because the expected markers are not exhaustive relevance judgments.
The benchmark does not measure synonym recall, multilingual relevance, adversarial
source reliability, medical/engineering correctness, or generated design quality.

## Method and next validation gates

The implementation uses [SQLite FTS5's BM25 ranking and Porter tokenizer](https://www.sqlite.org/fts5.html)
on source-body passages. Field ranks use the reciprocal-rank approach described by
[Cormack, Clarke and Büttcher](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf),
with application-specific coverage and duplicate controls. Those controls and
parameters still require broader evaluation; the cited research is not evidence
for FieldForge's performance.

CI checks these passage targets, verbatim offsets, duplicate suppression, missing
evidence, source corruption, cancellation, snapshot consistency during concurrent
updates and model-free desktop preview. Further release gates are independent
expert relevance labels, a held-out multilingual/adversarial set, precision metrics,
larger-corpus memory/latency measurements, and real local-model end-to-end evaluation.
