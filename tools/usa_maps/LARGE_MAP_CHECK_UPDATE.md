# Large-map verification and viewing update

The Connecticut/Maryland acquisition produced substantially larger visual/search indexes than earlier examples. Actual data exposed two separate issues:

1. The old 30-second full-index validation deadline was exceeded. Full-index `inspect_index` verification now receives a bounded 180-second connection deadline.
2. A whole-state viewport originally sorted every intersecting record before limiting the displayed subset. On Maryland this exceeded the unchanged 4-second interactive deadline and also prevented the combined search/view update. The corrected SQL limits spatial candidates first, then fetches and sorts only those candidates. Wide views still explicitly report limited detail; unseen features are not claimed absent.

The attached `large-map-checks.patch` changes one module. It does not remove or bypass SQLite `quick_check`, `rtreecheck`, schema validation, feature/spatial/search counts, source matching, file hashes, sidecar refusal, change detection, or cancellation. Ordinary visual/name queries retain their 4-second deadline; address queries retain 6 seconds. Very slow storage can still exceed the bounded verification deadline. No routing restriction handling changes.

## Exact source target

This patch targets the recent chat-delivered FieldForge regional-installer / USA map-manager source checkpoints. Those application modules are not all present on this branch's older application tree. This is not an application merge into main.

Original `fieldforge/navigation/regional_index.py` SHA-256:
`ce291560ac27c5804f3a9fd8a735e6d35ffe2e11e9c5ccb443d736fbd65bd7bb`

Final patched module SHA-256:
`c7004c801b86a32b66464650ff7e3df80ac0c3178189576242d5e717e0e3514f`

The earlier deadline-only intermediate module had hash `c005e71a5a0dfdb69a842c16b5f0aa6930ba5ac49f49d5c25af00f650106477f`; it is superseded and is not the final updater target. It did not fix the wide-view query.

Close FieldForge and source editors before modifying a local application copy. Back up the original module. Unknown, CRLF-converted, independently edited or frozen-executable versions require developer review rather than unconditional replacement. The accompanying chat delivery contains a hash-gated source updater with backup and idempotence checks; it does not download or modify maps or household data.

## Local tests completed

- 8 new backend tests prove the changed verification budget, preserved shorter interactive budgets, execution of all integrity SQL, rejection of damaged spatial/search indexes, deadline enforcement and cancellation.
- 7 new spatial-query tests check limits, read-only behavior, empty regions and bounded work. A deterministic SQLite instruction-budget negative control rejects the old global-sort query; the corrected query passes that same budget on a 12,000-record fictional test index.
- 28 updater tests pass, including actual Tk control invocation with controlled chooser/confirmation responses; unknown/custom files, symbolic/hard links, simulated Windows reparse attributes, existing locks/backups, disk failures and concurrent edits are tested. Simulated attributes are not Windows execution.
- Relevant existing backend/UI plus new suites: 286 passed under actual Tk/Xvfb.
- Acquisition/preparation tool tests repeated against the patched backend: 57 passed.
- The final patch applied to the exact original module and reproduced the final patched hash. New Python files parsed with Python 3.10 grammar; that is not Python 3.10 execution.

These are local Linux/Python 3.13.5 results: 371 targeted test cases total, not a new full-application run. No native Windows, physical receiver or driving-navigation verification is claimed by this patch. Final actual map ZIP and desktop results are recorded separately after completion.
