# Pocket Library — portable offline reading, not a native mobile release

The Knowledge Library now has **Pocket Reader…** beside Field Binder. It exports
the currently open article or all library bookmarks to a self-contained HTML
file with local title/body search, category filtering, light/dark views, three
reading sizes, accessible native controls and a one-article reading view. Its
responsive layout is designed for small screens as well as desktop browsers.
No Python, server, account, model or additional content download is needed to
read an already-exported file. Source generation still uses the desktop app.

## Use and limitations on phones

Open the desired article, or bookmark the articles to take with you. Choose
**Pocket Reader… → Build preview**, inspect the source list and full text,
confirm copying permission/privacy, then save a **new** `.html` filename. Copy
that file to the intended device. Open it in a browser that supports local HTML
and allows its built-in script. Use the search field, categories and article
list to read; source URLs are displayed as attribution, not opened automatically.

A phone's file manager, message attachment viewer or embedded preview may not
execute local HTML scripts or offer opening HTML in the preferred browser. This
export does not install itself as an Android/iOS app and has no share-sheet,
service worker or add-to-home-screen installation. Actual Android/iOS file-opening
workflows are not hardware-validated by this milestone. Test opening the saved
copy on your target device **before going offline**. A responsive browser test is
not equivalent to a native mobile release or Safari-on-iPhone certification.

All captured articles exist in the static HTML even without JavaScript. If the
script is disabled, incompatible or rejected by its content-security policy,
all full text remains readable with ordinary contents anchors and the browser's
Find command. Interactive controls appear only after initialization succeeds.
The file never says that information absent from this selected collection is
absent from the full FieldForge library or from the world.

Search is case/accent-normalized, all-term literal substring matching in titles
and article bodies, not semantic search, source metadata search, or an AI answer.
It has a 240-character input limit and a small input debounce. Category filtering
is exact. No matches hides the previous article so it cannot be confused with
a search answer. No stemming, translations or completeness guarantee is implied.
Contents links use generated in-file IDs and support keyboard navigation. Display
preferences and queries live only in the page's current memory; they are not
saved to localStorage, cookies, a database or a service. Reopening the file resets
them. This deliberately avoids relying on browser-dependent local-file storage.

## Content fidelity and source labels

This reuses Field Binder's one-transaction, read-only capture. There is a shared
limit of **50 articles and 8 MiB of body text**, with a **64 MiB rendered-file cap**.
Missing or checksum-invalid selected articles and excessive selections fail the
whole preview rather than silently truncating it. The Tk preview's labeled
20,000-character display limit does not shorten exported article bodies.

Each exported article includes its full text, category, source title/publisher,
supplied review and safety labels, reuse-rights field, and original body SHA-256.
No missing date, license or review claim is invented. The collection's timestamp
comes from the device clock. Captured text cannot silently change if the database
is edited after preview. Markdown and embedded HTML in a source remain literal
text, not executable or active markup. CR characters use HTML numeric references
to preserve the original DOM text, although fonts and visual wrapping vary.
PDF-derived articles retain their extraction warnings: this reader does not
recover their diagrams or validate tables, reading order or technical advice.

The original body hash identifies the captured article text; it is not the HTML
file hash and does not establish authorship, correctness or specialist review.
The export adds no reference corpus, no local LLM and no evidence of competence.
It is not a database backup, an importable JSON pack, a synchronized copy, or an
editor. Re-export when you need newer source versions.

## Privacy and security

Private article notes are **always excluded**, with no note-export option in the
Pocket UI. This remains independent of the older JSON-pack privacy checkbox.
Both capture and renderer reject attempts to include notes through the Pocket
API/UI path. Household, inventory, emergency, learning-progress and personal
reading-link records are not copied. The current article note is saved before
opening the exporter, but saving it never opts it into this reading copy.

Titles and article bodies can themselves contain private information; selecting
bookmarks also reveals your choice of references. The output is unencrypted and
readable by anyone holding it. Copy only material you have permission to store
and share. This is not a private-document vault, rights validator or automatic
redaction system. Browser history/extensions, operating-system previews and
printer spools have independent privacy behavior.

All source text and metadata are HTML-escaped. The only executable JavaScript and
stylesheet are fixed application-owned assets, each allowed by its exact SHA-256
CSP hash. There is no `unsafe-inline`/`unsafe-eval`, no untrusted HTML insertion,
no fetching, external fonts, images, service worker, external scripts or links to
remote resources. All contents links are generated local fragments. An unknown
URL fragment is ignored rather than becoming a selector, script or fetched path.
These are content-handling boundaries, not a defense against a malicious person
modifying both the exported document and its policy or a compromised browser.

## Saving, opening and printing

Pocket Reader reuses the tested exclusive-create HTML writer: existing files and
symlinks are not overwritten. Ordinary write/flush errors clean up only the
newly-created partial file. No hard links are required. Publication is not atomic;
a forced process exit or power loss can leave a partial new file. Success is
reported only after writing, flushing and fsync return. There is no claim of
hardware failure immunity or arbitrary filesystem certification.

Saving does not launch a browser or print. The desktop's separate confirmed open
action verifies the saved HTML hash before requesting the default browser. This
is a launch request, not proof the browser displayed the document. The reader's
**Print open article…** button explicitly invokes browser printing for the visible
article, including its provenance. Without JavaScript the browser can print the
static full collection. Check print preview and page count; physical printing
and every browser/printer combination are not certified.

The existing binder dialog provides preview cancellation, worker-thread capture/
save, normal-close protection during saving, and library note-save/busy guards.
Its original Field Binder behavior and private-note opt-in are unchanged. Small
hooks allow the Pocket dialog to reuse this lifecycle rather than duplicating it.
No database schema, dependencies of the deployed app, or archive format changes.

## Verification and development

Unit tests cover exact source retention, immutable capture, no private-note-column
reads, attempted note inclusion, missing/corrupt sources, size caps, escaping,
CSP hashes, new-file protection and hash-checked opening. Real Tk integration
exercises the actual Library button, pending-note saving, preview/save/close,
construction failures and existing guard behavior. The prior Binder regression
suite runs against the shared writer/lifecycle refactor.

The opt-in Playwright suite exercises offline loading, full DOM text, source
labels, literal search, categories, no-result states, keyboard focus, safe fragment
navigation, 320/390/768/1280-pixel layouts, large text, themes, explicit printing,
no-script fallback, CSP rejection of altered code, hostile source markup, and
absence of network/page-storage writes. CI has dedicated Chromium and WebKit
jobs using **local file URLs**, not a web server, with missing browser prerequisites
causing failure instead of silently skipping. Both block HTTP(S) requests before
opening the file and fail if the reader attempts network traffic. A negative
control verifies that this blocking really rejects a request. Chromium also uses
Playwright's offline emulation from initial navigation. For WebKit, request
blocking is used for the initial file load, then offline emulation is enabled
before interaction checks. The harness logs an independent plain, script-free
local-file probe with the offline flag on and off: some WebKit automation builds
reject even that plain file when offline emulation is enabled. This distinction
must not be presented as identical offline-emulation coverage across engines.
Source packaging waits for the browser jobs. Playwright and downloaded test
browsers are CI-only dependencies.

The development container blocks `file://` navigation by administrator policy.
Local browser checks use the generated bytes in memory instead, explicitly a
narrower rendering/interaction test; the policy is not changed or bypassed.
Local-file behavior must be observed in the CI jobs before claiming it passed.
Desktop/headless Linux and hosted Windows workflow checks remain distinct from
physical phone, native mobile, full screen-reader and printer validation.

Technical references consulted:
- https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/script-src
- https://developer.mozilla.org/en-US/docs/Web/API/Window/localStorage
- https://playwright.dev/python/docs/browsers

Update the application source to get the export button; old ZIPs do not update
automatically. Back up your database and close the old application before using
a new build. The generated reading file itself works without installing or
updating FieldForge.
