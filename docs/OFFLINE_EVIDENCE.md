# Offline evidence retrieval

Ask for relevant passages from articles already installed in the local library:

In the desktop **Knowledge Library**, choose **Find passages**, enter a question,
and select a result to inspect its source information. **Open full article** opens
the source in the reader and highlights the exact passage. Unsaved private notes
are saved before navigation. If an article changed after the search, search again
to obtain a passage from the new version. Search runs in a worker so the window
remains responsive.

The same operation is available from the command line:

```bash
fieldforge --database fieldforge.db knowledge-context "How do I store potable water?"
python -m fieldforge.knowledge --database fieldforge.db context "potable water"
```

The JSON result contains short verbatim passages, article slug and title, a
checksum of the complete article body, character offsets, source fields, review date, reuse rights,
and safety label. No network connection or model is needed. An empty `evidence`
array means the installed library did not yield a match. Stored article bodies
are checked against their checksums before being returned.

This is retrieval, not a generated answer or verification of the underlying
advice. Author-provided source and review fields may be incomplete or wrong.
Especially for high-stakes topics, inspect the full article, its original source,
and current expert guidance before acting. Personal notes are never searched or
included in this context output. The passage limit is 20; each passage is at most
1200 characters (360 by default). Retrieval considers up to 100 candidate articles,
ranked by distinct query-term matches. It scans overlapping windows through each
candidate's body, including late sections. This is lexical retrieval, so synonyms
or paraphrases without matching words can still be missed.

The output is a stable starting interface for a future on-device answer engine:
that engine must cite returned article IDs and avoid presenting unsupported claims.
