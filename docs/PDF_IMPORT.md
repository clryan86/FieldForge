# Preview-first PDF text import

## Delivered

The Knowledge Library's import row now has **Import PDF Text…** alongside the
existing plain-text importer. Choose a trusted local PDF, inspect an overview or
any physical page's extracted text, label its source/rights, and explicitly
accept the extraction and export/privacy notice before saving one article.
The existing article commit logic preserves notes and refuses to overwrite a
conflicting record. The old text importer keeps its existing behavior.

This is **text-layer extraction, not complete PDF preservation**. It does not
store original PDF bytes, render pages, recognize scans, extract pictures,
reconstruct tables, preserve annotations/attachments, or verify reading order.
The source PDF must be kept separately. A page can contain important diagrams
even when text was extracted successfully; a nonempty text layer does not prove
completeness. Compare the original before using technical or medical material.
Do not substitute this extracted article for the original procedure or manual.

Every saved article begins with these limitations and includes the original
PDF SHA-256, parser version, physical page count, and a marker for each page.
These page positions are not printed page labels. Pages without extracted text
are marked explicitly, not silently removed or declared blank. An entirely
textless file is rejected with an OCR-not-supported explanation. An error while
parsing any page aborts the whole capture, not a partially populated article.
Source hashes identify bytes; they do not authenticate a publisher or verify
extraction fidelity, advice correctness, or copying rights.

## Optional dependency and offline setup

From the **updated source folder**, before going offline:

```sh
python -m pip install ".[pdf]"
```

On Windows the `py` launcher can replace `python`. The `pdf` extra selects
`pypdf>=6.19.0,<7`. The interface's PDF setup help explains installation but never
installs anything automatically or downloads models. Core FieldForge remains
usable without this optional dependency; PDF attempts report a missing dependency
instead of making the whole application fail. Use the declared dependency range
for deployed installations. An older installed parser is not automatically
upgraded by opening the screen; the extraction header records its actual version.

No network request is made by the extractor. User-selected cloud/network-mounted
filesystems may still contact their provider; use an already-local file offline.
This is not an Android/iOS PDF implementation or a packaged installer.

## Capture, limits and process lifecycle

The input must be a regular `.pdf` file with a PDF header, at most **16 MiB**.
It is read once into captured bytes, so later source-file edits/deletion do not
silently change the preview or the imported article. A subprocess receives
those bytes through temporary handles, never a user-supplied command or filename.
Only a fixed Python module is launched, without a shell. No database path is
passed to the parser. Pypdf is used in strict mode. Encrypted PDFs are rejected;
this workflow does not ask for or store passwords or bypass access controls.

A maximum of **200 physical pages**, **1,500,000 extracted characters**, and
**8 MiB of worker output** is accepted. A page content-stream check rejects
streams exceeding 8 MiB *after decompression*. That check is not a guarantee
that parsing/decompression has low peak memory. The parser is a disposable child
with a parent-enforced 20-second default processing deadline. Closing during
extraction signals cancellation; the child is killed and reaped and no article
is saved. Normal close during a commit remains blocked until the result is known.

On POSIX the worker also sets 768 MiB address-space and 20-second CPU limits,
and disables core dumps. **Windows does not receive that address-space cap**;
its separate-process deadline/output/input limits are not an equivalent memory
sandbox. Process separation is a reliability boundary, not a security sandbox.
Only process trusted PDFs. Malformed data or resource limits produce failures,
not invented content. Input filesystem I/O and an uninterruptible OS operation
can exceed the parser deadline. Temporary files contain unencrypted private
bytes and are cleaned normally, not securely erased; forced exit/power loss can
leave remnants. No hardware-level crash/memory guarantee is claimed.

The on-screen text preview is capped at 20,000 characters per view and labels
that truncation. Its page picker can inspect later pages. The saved article
contains all captured page text and markers within the stated limits, not only
the currently viewed page. The UI does not open original PDFs or execute their
embedded JavaScript, source links, or commands. It also does not visually verify
the extracted words or attempt OCR.

## Privacy, metadata and repeated imports

The filename suggests an editable title but the source path is not persisted.
Embedded PDF author/title/date claims are not automatically promoted into
article metadata. Source, publisher, review date and rights start unknown. The
default caution label is not independent content classification or approval.

The default ID is `pdf-` plus the original PDF hash. An identical article under
that ID imports as unchanged. A new parser version, changed source metadata, or
user-edited body can conflict even for the same PDF; this produces an explicit
no-overwrite error. A different ID intentionally creates a separate record.
There is no automatic edition manager, bulk intake, page-range selection or
cross-format duplicate detection in this version.

**Extracted text becomes an ordinary searchable/exportable article, not a private
note.** It is included in ordinary knowledge packs and full database snapshots.
The original PDF file and pictures are not included in those snapshots by this
feature. Private article notes retain their separate existing rules. Do not
import passwords or private medical/household records here. A copying-rights
checkbox is not legal validation, and no content is labeled public domain or
reviewed merely because it was imported.

Opening the dialog first saves the current article note and holds the existing
library busy/close guard. A successful import clears hiding filters and refreshes
the list. This change does not migrate the database or alter article-pack format.

## Verification scope

Targeted tests cover real generated PDF extraction in the subprocess, page
ordering/missing text, encrypted/malformed files, input/character/stream/output
bounds, unsupported shapes, cancelled/timed-out child cleanup, invalid worker
responses, no automatic source claims, captured-version consistency, original
path privacy, idempotent/conflicting imports, real Tk consent/page-picker/save
flows, the existing plain-text flow, and visible controls.

Four full-checkout integration cases exercise Ask Library, article-pack roundtrip,
complete recovery of articles/notes, and the real Knowledge Library PDF button
with pending-note and refresh guards. Existing GUI/platform jobs include these
cases and require both pypdf and working Tk. Outcome claims must use the exact
commit's observed CI result, not merely the addition of tests.

The local development container currently supplies pypdf 5.9.0 and cannot fetch
6.19.0 from its package index. Local runs therefore use the older parser only
against generated trusted test PDFs; they are compatibility checks, not a
recommendation to deploy it. CI installs the declared modern extra separately.
The local repository clone also fails due to DNS, so locally tested files are a
verified fetched source subset, not a full checkout. Full regressions, lint,
build and declared-version platform checks are performed in CI.

Update source code to get the new button. Downloaded ZIPs do not auto-update and
importing JSON content cannot install this feature. Back up your data and close
the old application before changing builds.

Technical references consulted:
- https://pypdf.readthedocs.io/en/6.19.0/user/extract-text.html
- https://pypi.org/project/pypdf/6.19.0/
- https://docs.python.org/3/library/subprocess.html
