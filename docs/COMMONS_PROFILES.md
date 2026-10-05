# Local Commons profiles, photos, and member directory

Saved local accounts can now edit a profile, keep a private photo, and choose
what to share in the **Member directory**. Profiles start private. Joining chat,
creating an account, or uploading a photo does not publish a directory listing.

This feature runs in the existing Commons preview on the same computer. The
server binds to `127.0.0.1`; public hosting and a public membership service are
still unfinished. Accounts belong to their local database. Names, interests,
experience answers, and qualifications are self-reported and unverified.

## Open your profile

Follow the [preview launch instructions](COMMONS_CHAT_PREVIEW.md#start-it), then
open [the local Commons page](http://127.0.0.1:8765/commons). If you selected a
different port, use that port in the address.

1. Choose **Create account** or **Sign in**. An existing guest can choose
   **Save my account** to keep the current participant and inbox. The
   [account guide](COMMONS_ACCOUNTS.md) explains passwords, recovery codes,
   and returning to the same account.
2. Choose **My profile**. A guest sees **Save my account to add a profile**;
   a saved account sees the editor.
3. Enter a **Profile display name** of up to 60 characters and optional
   **About you** text of up to 500 characters. The account's `@username` stays
   the same in chat and also appears on a shared directory profile. A profile
   display name does not rename the account or change message ownership.
4. In **Interests & experience**, choose up to five areas and select an
   experience answer for each. In **How would you like to help?**, choose any
   of the five supported ways to contribute: hands-on help, teaching,
   coordinating, research, and remote help.
5. Review **Your sharing choices**, then choose **Save profile**. Leaving all
   sharing choices unchecked keeps the profile private.

There is no automatic profile save. The form holds unsaved edits in the current
view. Closing it, reloading the saved profile, or leaving the session can discard
those edits. Photo uploads and removals are separate actions described below.

## Your sharing choices

| Choice in the editor | What participants can see after saving |
| --- | --- |
| **List my profile in the local Commons directory** is unchecked | The profile is absent from directory results. Its saved answers and photo remain available to its account through the editor and profile export. |
| **List my profile in the local Commons directory** is checked | Other joined participants on this server can see the profile display name, account `@username`, and bio. This includes signed-in guests browsing the directory. |
| **Share my interests and ways to help** is checked | When the profile is listed, selected interest badges and ways to help appear with it. Private experience answers are not published. |
| **Share my profile photo** is checked | When the profile is listed, its current normalized photo can be requested by participants allowed to view the listing. A saved photo is required to select this choice. |

Shared interest badges follow the saved selection order. Changing a private
experience answer does not rank or reorder the public badges. Every badge
remains self-reported and grants no credential, administrative role, or other
privilege. The profile questionnaire is separate from the optional chat account
skill label.

The directory and photo choices work together: skills and photos become visible
only while the profile is listed. Unchecking the directory choice and choosing
**Save profile** withdraws the listing. The other checkboxes can remain selected
while a profile is private, so review all three choices before listing it again.

These controls govern access through the local application. Saved private
answers and normalized photos reside in its SQLite database; someone with
access to the server's files or its backups is outside that interface boundary.

## Add, replace, or remove a photo

Photo handling uses the optional Commons dependencies. From the source checkout,
install them in the Python environment used to run the preview, then restart it:

```sh
python -m pip install ".[commons]"
```

The Commons extra includes `Pillow>=12.3,<13` for photo processing and the
existing authenticator dependency. Text profiles and the directory work without
photo support. If the decoder is unavailable or configured to accept truncated
images, the editor reports that photo uploads are unavailable.

In **Profile photo**, choose **Choose a photo from this device**, select an
image, then choose **Upload photo privately**. Uploading immediately saves the
normalized photo and retains other unsaved form edits in the current editor.
Those other edits still need **Save profile**.

Every new upload starts private, including a replacement for a previously shared
photo. To share the new image, select **Share my profile photo** and choose
**Save profile**. The old photo's asset ID stops working after replacement.

| Photo property | Limit or behavior |
| --- | --- |
| Accepted inputs | Still PNG, JPEG, and WebP images |
| Original upload size | At most 1 MiB, or 1,048,576 bytes |
| Original dimensions | At most 4,096 pixels on each side and 12,000,000 total pixels |
| Saved image | A centered square PNG, at most 256 × 256 pixels and 250 KiB |
| Orientation and transparency | EXIF orientation is applied before cropping; alpha transparency is retained |
| Small originals | Cropped without enlarging them |
| Highly detailed transparent images | May be reduced to 240 × 240 pixels to stay within the saved byte limit |
| Rejected inputs | Animation, multiple-frame images, unsupported formats, malformed or truncated files, invalid base64, and images exceeding the limits |

The server decodes the image and copies its pixels into a fresh image. Embedded
EXIF/GPS information, XMP, text, ICC profiles, comments, and other source metadata
are excluded from the saved PNG. Uploaded originals and original filenames are
not retained in the database. Selecting a file does not change or delete the
original on your device. Visible writing or location details in the pixels
remain part of the picture.

Choose **Remove photo** and confirm to remove the saved photo immediately.
That also withdraws the photo from the directory and clears photo sharing.
Other saved profile details remain, and other draft edits still need to be saved.

Photo reads use an authenticated API request with a fresh visibility check;
there is no public photo download URL. Knowing an old or current asset ID does
not grant access. A profile owner can read their private saved photo through
their valid session. Other participants need an active, shared listing with
photo sharing enabled and no blocking relationship.

## Browse the member directory

After joining the local preview, choose **Member directory**. A saved account is
required to create a profile; guests can browse profiles that members chose to
share.

Use **Search member profiles** to search a display name, username, or bio with
up to 60 characters. Use **Interest area** to filter shared interest badges.
Hidden skill selections do not produce category-filter matches. Results contain
up to twelve profiles per page; use **Previous** and **Next** for more results.

Results refresh when you open the directory, search, change pages, or choose
**Refresh directory**. The directory excludes private profiles, suspended
participants, and participants blocked in either direction. It does not expose
contact codes, session tokens, private experience answers, or private profile
questionnaires. A separate opaque profile ID supports directory actions.

Choose **Block @username** on another member's card and confirm to use the
existing chat block action. The two participants' directory listings and shared
photos become unavailable to each other on subsequent requests. The existing
private-message blocking behavior also applies, including consumption of
pending open-once deliveries. See the
[private-message guide](COMMONS_PRIVATE_MESSAGES.md) for those delivery rules.
The interface points to **Community rooms** for existing unblock controls.

Withdrawals, replacements, deletion, and blocking apply to new requests. They
cannot erase a response already received, a picture currently displayed in
another view, screenshots, exports, or other copies someone kept. Reopening or
refreshing the directory retrieves its current state.

## Conflicting edits and account changes

Profile saves, photo changes, and deletion carry the revision of the saved
profile that the editor loaded. If another tab or request changed it first,
the server rejects the stale change. The editor shows **Your saved profile
changed** and retains the draft in that view.

Use **Reload saved profile** to retrieve the current version. Its confirmation
explains that this replaces the draft; preserve any draft text you still need
before reloading. Changes are not silently merged or reapplied over newer data.

Ordinary tabs in one browser profile share the Commons session cookie. The
browser includes its displayed participant ID on established-session requests.
A request whose cookie now belongs to another participant is rejected, so an
old view cannot submit its draft under a newly signed-in account. Photo uploads
also recheck the session and profile revision after image processing, before
the database write. Signing out, suspension, or a concurrent profile edit can
therefore cancel an upload that was already processing.

## Export and delete your profile

**Export my profile** downloads `fieldforge-commons-my-profile.json`. It contains
the saved profile, including private questionnaire answers, its sharing choices,
the normalized photo as base64 when present, and an export timestamp. Unsaved
form edits are excluded. Profile exports do not contain passwords, recovery
codes, or session tokens; message exports remain separate.

**Delete my profile** asks for confirmation, then clears the saved profile
details, questionnaire answers, sharing choices, and normalized photo. It removes
the directory listing and invalidates its photo and public profile identifiers.
The database retains an empty revision marker associated with the account so
an old editor cannot restore deleted data with a stale save. Creating a new
profile starts private and issues a new public profile ID.

Deleting a profile keeps the local account, password and recovery mechanism,
contact code, inbox, messages, and blocking relationships. **Account deletion is
not implemented yet.** Profile deletion cannot recall prior downloads or copies
and does not erase separate database backups. A restored backup may contain an
earlier profile state.

## Database upgrade and implementation boundaries

Profiles introduced Commons database schema version **5**; the current inbox
lifecycle update uses **version 6**. Opening an existing supported Commons
database with the updated preview adds the profile table
while retaining accounts, sessions, room messages, private conversations,
invitations, blocks, reports, and owner configuration. Existing accounts do not
automatically receive a directory listing.

Stop the server and back up the local database before upgrading. Continue using
the same database path to retain the existing community. Use the updated code
for both preview and owner commands; older releases that do not understand
schema version 6 must not operate on the upgraded file. Current owner utilities
preserve the version instead of downgrading it. Keep databases and their private
contents outside the source repository.

Version 6 also records invitation retries and reclaims private conversations
after their last eligible member leaves. It does not remove saved accounts or
their profiles/photos. See the [private inbox guide](COMMONS_PRIVATE_MESSAGES.md)
for invitation limits and guest membership expiry.

Profile operations require an authenticated local session. Edits and exports
operate only on that session's saved account. The owner console does not bypass
another profile's privacy or photo-sharing rules. Directory and photo reads
check current suspension and blocking state.

The HTTP layer retains same-origin, JSON, custom-header, and no-store response
protections. Only photo uploads receive the larger bounded JSON request limit;
profile saves allow room for a fully JSON-escaped Unicode biography, and other
APIs keep their smaller limits. The displayed-participant header binds browser
actions to their account context while the session cookie remains the
authentication credential.

Photo decoding occurs after authentication, with at most two decodes running
per preview instance. The normalizer does not alter process-wide Pillow decoder
settings or warning filters. Image-library execution is in process; OS-level
decoder isolation and production deployment controls remain future work for a
public service. The preview continues to run only on loopback.

The implementation was checked against these primary Pillow references:

- [Pillow security guidance](https://pillow.readthedocs.io/en/stable/handbook/security.html):
  accepted-format restrictions, image-size limits, and metadata handling.
- [Image module](https://pillow.readthedocs.io/en/stable/reference/Image.html):
  lazy opening, verification, reopening before loading, and decompression limits.
- [ImageOps module](https://pillow.readthedocs.io/en/stable/reference/ImageOps.html):
  EXIF transposition and centered cropping/resizing.
- [Image file formats](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html):
  strict truncated-file behavior, PNG metadata, and APNG/multiframe handling.

## Verification

On 2026-10-05 UTC, the combined Commons, profile/photo, community, and portal
suite passed **259 tests and six subtests**, including **22 Chromium browser
tests**. One existing graphical portal handoff test was skipped because the
local environment has no native graphical desktop. The suite completed in
151.84 seconds. Repository-wide Ruff, JavaScript syntax, and whitespace checks
passed.

The seven new profile browser tests exercise the editor and directory at desktop
and 390-pixel widths. Five new shared-session browser regressions cover account
switches, sends before the next poll, cross-account credential-change rejection,
and delayed successful/failed responses. The ten existing chat, private-message,
account and owner browser tests also pass.

The built wheel was installed outside the source checkout. Its packaged source
and profile assets matched the checked files. Private profile saving, normalized
photo upload, directory publication, authenticated photo reading, HTTP assets
and database restart passed from that installation. A separate `python -S` run
verified account creation, text profiles, the directory and static assets without
optional packages. Native Windows/macOS execution and public hosting have not
been verified by these checks.

Coverage includes default privacy, separate skill/photo consent, guest access,
photo ownership and replacement, blocking and suspension, revision conflicts,
deletion and export, database migration, browser-account request binding,
bounded HTTP inputs, malformed images, metadata removal, animation rejection,
dimension limits, optional decoder behavior, and concurrent normalization.

```sh
FIELDFORGE_PORTAL_BROWSER_TESTS=1 python -m pytest -o addopts='' -q -ra tests/test_commons_*.py tests/test_profile_photos.py tests/test_community_profile.py tests/test_online_portal.py tests/test_online_integration.py tests/test_portal_connection.py
```

Browser checks require Playwright and Chromium as described in the chat guide.
All photo fixtures are generated test images. No personal photos are used by
these tests, and no real owner account or credentials were provisioned.
