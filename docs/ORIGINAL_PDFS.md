# Preserve original PDFs, including diagrams and scans

**Knowledge Library → Original PDFs…** keeps an exact captured PDF byte sequence
inside the current SQLite database, independently of extracted article text.
Original images, vector diagrams, fonts, layout, annotations, file metadata,
attachments, encryption and any active content remain in those bytes. FieldForge
neither interprets nor modifies them in this workflow. An exported original can
be opened manually with a compatible trusted PDF viewer; no viewer is bundled or
launched automatically. A saved file can be damaged or unsupported despite having
a PDF header: preserving bytes is not validating the file's structure or content.

## Store and recover a file

Choose **Original PDFs… → Choose local PDF…**. The metadata preview shows its
filename, captured byte count and SHA-256. This is not a page-rendering preview.
Confirm that you trust the source, have permission to copy it and accept the
unencrypted storage notice. Choose **Store captured original**. File selection
alone does not add a stored file. Source paths are not persisted, and no household
names or document contents are inferred from the user's accounts.

Original PDFs can be stored without an article, including scanned documents for
which the text importer returns no readable text. These files are browsable by
filename in Original PDFs, not full-text searchable. There is no OCR, automatic
article creation or automatic document download. The existing PDF text importer
continues to require its optional parser; byte preservation uses only Python's
standard library and works without that parser installed.

To associate a PDF with an article, first open that article in Knowledge Library,
then open Original PDFs and select **Associate with the article open in the
Library** before capturing the file. The association is a user choice, not a
verified match between the article and PDF. It never validates the article's
extraction, restores pictures into its text, changes review/rights labels, or
updates practice records. Changing that checkbox clears an existing capture and
its confirmation so a stale selection is not silently repurposed.

A capture holds at most 16 MiB of bytes in memory. Store uses that capture even
if the external file is later moved or deleted. The reader compares file size
and modification metadata before/after reading to reject ordinary concurrent
changes. This is not filesystem locking or protection against a malicious local
writer who can race or restore those attributes. A checksum identifies the bytes
actually captured, not author identity, copying rights, valid PDF syntax or safe
instructions. Retain independent backups and verify meaningful documents in your
normal trusted viewer.

Select a stored reference and choose **Verify bytes** to check its complete stored
payload against its SHA-256. **Export original PDF…** separately confirms copying
permission/privacy and writes to a new `.pdf` path, then reads it back and compares
it with the verified stored bytes. Existing paths, including symlinks, are not
overwritten. Corrupt or missing stored bytes fail before creating an export.
Nothing is opened, printed, decrypted, or executed by these operations. Manually
opening the resulting PDF is a separate action with the viewer's own behavior.

## Storage, versions and duplicates

Two additive, versioned tables are created on first opening of this workflow:
`knowledge_original_blobs` (content-addressed binary payloads) and
`knowledge_original_refs` (filenames and optional article associations). An
independent `original_files_schema=1` marker is stored in `knowledge_state`.
Existing incomplete/unversioned/future schemas fail instead of being reset.
No existing article, annotation, inventory or household table is migrated.

A single stored byte sequence is shared when associated with multiple articles
or also retained without an article. The same hash/article combination is a
no-op after verifying the existing bytes; its first filename and association
remain unchanged even if the selected external filename differs. A hash match
never silently repairs damaged stored data. Use trusted recovery copies instead.
Limits apply to **16 MiB per PDF, 256 MiB of unique stored PDF bytes and 500
references per database**. These are intentional initial implementation bounds,
not a capacity or performance claim for a civilization-scale document archive.

Associations capture an article version from its stored body hash and metadata.
The article's full body is validated before making an association; later listing
compares hashes/metadata only, not every article or original's complete bytes.
Private annotation changes do not alter an article version. A changed or removed
article is flagged, but its original PDF remains exportable. No cascading delete
from articles is allowed. Exact reuse of an earlier article's content is treated
as the same version; this is not a revision-history archive.

The interface supports multiple original files per article, but does not edit
or automatically refresh an existing association to a different article version.
A second capture of the same PDF/article with a different version is rejected
without replacing the earlier association. To deliberately replace that
association, export/retain any needed copy, remove the old stored reference and
capture it again, or keep the original unassociated. Associated source metadata
is a snapshot, not evidence that the linked article was generated from that PDF.

Writes use one SQLite transaction for blob, reference, deduplication and capacity
checks. Concurrent duplicate storage makes one reference; failed reference
insertion rolls back its new blob. Export/remove checks reference IDs and content
tokens so stale selections cannot target changed records. Once export captures
verified bytes, a later deletion in another process does not revoke that captured
copy. Application operations are not a defense against arbitrary external SQL
changes or a malicious local administrator.

## Removal and privacy

**Remove stored reference…** requires confirmation. It removes the selected
reference and, only when no references remain, deletes the live blob record.
It does not delete the external original, other associations, article bodies,
annotations or previous backups. SQLite may retain deleted data in free pages,
journals, WAL files and old snapshots, and the database file may not shrink.
Removal is not secure erasure. No automatic vacuum, permanent deletion, hidden
history copy or unencrypted-to-encrypted conversion is implemented.

All stored files and metadata are unencrypted. Original PDFs may contain personal
metadata, attachments, hidden layers, scripts or private data absent from extracted
text. This workflow preserves rather than strips those elements. Do not treat it
as a secure vault, sanitizer, malware scanner or permission checker. The trust
confirmation is not technical verification. Only open trusted PDFs in a suitable
viewer; FieldForge does not choose your viewer's security behavior.

Ordinary article JSON packs, Field Binder, Pocket Reader and Ask Library do not
query these original-file tables. Storing an original therefore does not quietly
add its binary content, filename or association to public article exports. An
article body or title that already contains private details or a file hash still
exports under that feature's existing rules. No automatic redaction is claimed.

**Full SQLite snapshots include all stored originals**, even when the external
file is missing. Recovery previews add original-file/reference counts if these
tables are present, while older databases' summaries remain compatible. The
archive/SQLite integrity checks validate the archive and database structure, not
all individual stored PDF hashes; Verify bytes or Export checks those after
recovery. The older household-only JSON export does not include originals.
Backups become larger and may take longer; existing snapshot size, timeout and
filesystem constraints still apply. An external file merely passed through PDF
text import is not automatically part of a full snapshot.

## Interface, timing and verification

Originals operations use a worker thread; Tk widgets stay on the main thread.
Opening the manager first saves the pending Library article note and holds the
existing normal-close/tab/backup guard. Closing during a capture/read discards
its result without a stored original. Normal closing is blocked during Store,
Export and Remove until the write result is known. File/SQLite operations are
bounded in size with a 250 ms database lock wait, but are not forcibly cancellable
I/O or a hard deadline on a remote/stalled filesystem.

Exclusive output creation does not require hard links. Successful export is
reported after write, flush, fsync and read-back comparison. Publication is not
atomic: other processes may see an incomplete new file during writing, and power
loss or forced termination can leave a partial file. Normal errors clean up only
the new file identified as created by this operation. This is not a hostile-local-
filesystem race defense or power-loss guarantee.

Tests cover metadata/data bounds, literal search/paging, scans/encrypted and
active-content fixtures stored without parsing, byte-accurate restoration,
unchanged source/path snapshots, deduplication, stale associations, missing
articles, corrupted blobs, transaction failures, capacity limits, export consent,
no-overwrite/no-network behavior and actual Tk workflows. Full integration checks
include genuine PDF vector drawings/attachments and full snapshot recovery,
private export separation and the actual desktop close/backup guards. Generated
fixtures contain no private user data or copied manuals. Rendering inspection
is separate from byte-preservation testing and not general PDF-viewer validation.

Technical implementation references:
- Python sqlite3 transactions and backup: https://docs.python.org/3.13/library/sqlite3.html
- SQLite online backup: https://sqlite.org/backup.html
- SQLite BLOB storage tradeoffs: https://www.sqlite.org/intern-v-extern-blob.html

The choice of in-database bytes keeps original files within the existing full
snapshot boundary. It is not a claim that BLOB storage is faster than external
files for large manuals; hardware/filesystem benchmarks and a larger content
architecture remain future work. Update source for this feature: old ZIPs do not
auto-update, and article JSON cannot install this screen. Close the old app and
back up the database before changing builds. No native mobile release, new
reference corpus, local AI model or signed installer is added here.
