FIELDFORGE — WINDOWS x64 DEVELOPMENT BUILD

START HERE
Extract the entire ZIP to a NEW folder. Open the extracted FieldForge-Windows
folder and double-click FieldForge.exe. No separately installed Python, pip,
PDF parser or internet connection is needed to run this packaged edition.
Keep FieldForgeTools.exe and the entire _internal folder beside FieldForge.exe.
Do not run from inside the ZIP, or copy only the main executable.

This is an unsigned development folder, not a signed installer, production
release, verified publisher certificate or automatic update. It is built for
64-bit Windows. Hosted Windows tests do not certify all Windows versions,
Windows ARM emulation or your particular computer. Never disable antivirus or
other Windows security protection to run a download you do not trust.
No administrator installation, file association, registry change or background
service is performed by the FieldForge launcher.

BLUEPRINTS
The Blueprints tab is beside Dashboard. Choose Create layout from dimensions,
name the layout, enter a part's material, XYZ size and XYZ position, and select
Add part. Repeat for more parts, then Create drawings. Save the design or export
its offline report, SVG sheets and CSV tables from the engineering workspace.
Sizes accept mm, cm, m, in and ft. No AI model or network is needed for this path.
The Engineering, Projects and guides, and Software architecture buttons open
the three makers. AI generation requires a separately installed Ollama model.
These are draft layouts: rectangular part envelopes, not joints, structural
analysis or fabrication-ready CAD. Real-model design quality is not benchmarked.

YOUR EXISTING DATA
The default is %USERPROFILE%\.fieldforge\playground.db, matching the existing
Start FieldForge.cmd source launcher. FIELDFORGE_DB overrides the default.
An explicit --database path overrides that environment variable for this run.
Open Help → Build & data location to see the exact database used by this window,
the tested source commit and branch commit. Backup & Recovery also shows the
active database path. A build label is not cryptographic proof of authenticity.

No database is copied into this download. No household, place, note or incident
records are seeded. If your earlier setup used fieldforge.db or another path,
point the new app at THAT path; do not delete either file because a different
window appears empty. Changing the application folder does not move data.
The word portable describes the software folder, not the data-storage location.

Example from PowerShell (replace the path with your verified database path):
  .\FieldForge.exe --database "D:\FieldForge-data\my-library.db"

The first run can initialize the chosen database using the existing app logic.
It does not merge, scan for, import or reset other databases. Before changing
builds, save a full verified backup, close the old application, and keep its
source/application folder until the new version works with your chosen data.
Never copy a live SQLite file as your only backup; use Backup & Recovery.

RECOVERY AND DIAGNOSTICS
Open Recovery.cmd starts the recovery-only screen, including when the current
application database is unavailable. It does not initialize a missing database.
Choose a trusted .ffbackup to inspect and restore to a NEW database. Open recovered
copy launches the same packaged FieldForge.exe using that recovered file. The
original window and its default database setting are not changed.

Check Installation.cmd runs opt-in checks on generated temporary examples, not
your selected database. It checks bundled lessons, PDF text extraction through
the helper process, original PDF preservation, full snapshot recovery, portable
HTML generation, map tile reading and Tk image decoding. On Windows it also opens
the blueprint form, creates a layout and verifies saved/exported geometry. It opens
and normally closes a recovered desktop and the recovery-only window. Temporary
files are removed normally, not securely erased. No diagnostic report is uploaded
or automatically written into your application database. The command prints its
result in a local console. A passing smoke test is not certification of every
feature, operating system, printer, PDF or map file.

CONTENTS AND LIMITS
The 12 starter articles and 20 Foundations lessons are bundled but remain
explicit library-installation choices. Use Load Starter Library or Foundations
Pack inside Knowledge Library. A separate 439-article reference collection,
including 172 original Education Foundations lesson drafts, is bundled. It is
installed automatically only into an empty library; existing libraries offer
Install Reference Library. The lesson drafts have not had independent educator
review or demonstrated learning-outcome evaluation. There is no specialist-reviewed civilization
corpus, local language model, native mobile app or new map collection in this ZIP.
The standard PDF-text parser, serial adapter and Pillow image codecs are included. Encrypted-PDF extraction is still
unsupported; original-file storage preserves those bytes without decryption.
Read and retain the existing source/extraction warnings for technical references.

Maps opens supported already-local PNG/JPEG/WebP MBTiles files. Navigation opens
the combined GPS workspace and a separate uncalibrated map-image viewer. The
serial adapter and Pillow image codecs are included; nothing connects or records
automatically. See docs/GPS_WORKSPACE.md in the source for format limits. Map packs stay external
and are NOT included in database backups; keep independent copies and licenses.
Full database backups include original PDFs only when explicitly stored through
Original PDFs. The application folder is not a backup of your data or documents.
Databases, exports and snapshots remain unencrypted. Unchanged original PDFs can
contain active/private content. Only open files you trust in appropriate software.

BUILD AND DEPENDENCIES
Two executables keep graphical startup separate from the console-capable PDF
protocol. The PDF helper receives captured bytes through redirected temporary
handles, not a shell command or arbitrary module name. Missing helper files cause
an explicit failure, never fallback to an unknown Python installation.
Existing parser input/output/time limits and cancellation remain in effect.
Packaged recovery starts an independent graphical process.

The build uses PyInstaller 6.22.3 on Windows x64 with Python 3.13.16. The installed
pypdf comes from the project's declared >=6.19.0,<7 optional range. Build-only
packages are not new application requirements for source users. Python 3.13.16
is the September 30, 2026 maintenance/security release; the Windows 3.12 source
compatibility job does not supply the runtime distributed in this archive.
Both source compatibility on Windows 3.13.16 and the frozen binary smoke test
are required. No fallback to an older packaged interpreter is allowed. Component
license texts are included under THIRD-PARTY-NOTICES. When the Windows Python
installer omits standalone Tcl/Tk terms, exact upstream copies are accepted
only for runtime 8.6.15 after checksum verification; their provenance is included. This milestone does not
choose or change the FieldForge project's redistribution license.

CI tests the copied application from a new path with spaces/Unicode, away from
source, with installed Python and Tcl/Tk settings removed from the child PATH
and environment. It requires actual PDF extraction and responsive desktop
subprocesses, verifies inherited user-data paths are untouched, and checks that
removing the helper produces an explicit failure. The application files must
remain unchanged during diagnostics. Only then is a ZIP produced. The ZIP's
SHA-256 is in the companion .sha256 file; compare it before using a transferred
copy. A hash verifies equality, not publisher trust or malware safety.

The source tree continues to support its original Python launch paths. Source
users are not required to install PyInstaller. Windows binaries cannot be
validated by running a Linux source checkout; final Windows build/test results
must be observed in the matching GitHub Actions run.

Technical references consulted:
https://pyinstaller.org/en/stable/runtime-information.html
https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html
https://pyinstaller.org/en/stable/spec-files.html
https://pyinstaller.org/en/stable/license.html

Pinned Python runtime reference:
https://www.python.org/downloads/release/python-31316/
