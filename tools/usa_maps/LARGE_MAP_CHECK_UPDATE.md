# Large-map verification update

The Connecticut/Maryland acquisition produced substantially larger visual/search indexes than earlier examples. The old 30-second full-index validation deadline was exceeded on actual data. The attached `large-map-checks.patch` changes **only** the full-index connection deadline in `inspect_index` from 30 to 180 seconds.

This does not remove or bypass SQLite `quick_check`, `rtreecheck`, schema validation, feature/spatial/search counts, source matching, file hashes, sidecar refusal, change detection, or cancellation. Ordinary visual/name queries retain their 4-second deadline; address queries retain 6 seconds. Very slow storage can still exceed the bounded verification deadline. No routing restriction handling changes.

## Exact source target

This patch targets the recent chat-delivered FieldForge regional-installer / USA map-manager source checkpoints. Those application modules are not all present on this branch's older application tree. Do not describe this as an application merge into main.

Original `fieldforge/navigation/regional_index.py` SHA-256:
`ce291560ac27c5804f3a9fd8a735e6d35ffe2e11e9c5ccb443d736fbd65bd7bb`

Patched module SHA-256:
`c005e71a5a0dfdb69a842c16b5f0aa6930ba5ac49f49d5c25af00f650106477f`

Close FieldForge and source editors before modifying a local application copy. Back up the original module. Unknown, CRLF-converted, independently edited or frozen-executable versions require developer review rather than unconditional replacement. The accompanying chat delivery contains a hash-gated source updater with backup and idempotence checks; it does not download or modify maps or household data.

## Local tests completed

- 8 new backend tests prove the changed verification budget, preserved shorter interactive budgets, execution of all integrity SQL, rejection of damaged spatial/search indexes, deadline enforcement and cancellation.
- 26 source-updater tests pass, including actual Tk control invocation with controlled chooser/confirmation responses; unknown/custom files, symlinks/hard links, existing locks/backups, disk failures and concurrent edits are tested.
- Relevant existing backend/UI plus new deadline suite: 279 passed under actual Tk/Xvfb.
- Acquisition/preparation tool tests repeated against the patched backend: 57 passed.
- The one-line patch applied to the exact original module and reproduced the patched hash. New Python files parsed with Python 3.10 grammar; that is not Python 3.10 execution.

All of these are local Linux/Python 3.13.5 results. No native Windows, physical receiver, full-application or driving-navigation verification is claimed by this patch. Final actual map ZIP validation results are recorded separately after completion.
