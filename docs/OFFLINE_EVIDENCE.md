# Offline evidence retrieval

Ask for relevant passages from articles already installed in the local library:

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
about 1200 characters, with a small extension to avoid cutting a word.

The output is a stable starting interface for a future on-device answer engine:
that engine must cite returned article IDs and avoid presenting unsupported claims.
