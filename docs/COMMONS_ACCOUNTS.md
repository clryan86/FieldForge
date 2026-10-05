# Local Commons accounts

Commons supports saved local accounts, password sign-in, recovery with a private
code, complete retained-data exports, and permanent self-service closure.
Your participant ID, contact code, private inbox,
invitations, blocks, and message ownership survive sign-out, session expiry,
and server restarts **when you keep the same database**.

This is still the loopback-only preview. It is not a public account service,
email service, or social sign-in integration. Accounts on different database
files are separate. No real-world identity or professional qualification is
verified by creating an account.

![Local account with a retained private inbox](images/commons-account-preview.png)

This screenshot comes from a browser test using explicitly named TEST users
and messages. It contains no passwords or recovery codes.

Saved accounts can now use [My profile](COMMONS_PROFILES.md) for an optional
profile, photo and self-selected interests. A profile starts private; publishing
it, sharing skills and sharing a photo are separate choices. Deleting a profile
keeps the local account, inbox and contact code.

## Try it

Use the [local preview launch instructions](COMMONS_CHAT_PREVIEW.md#start-it).

1. On the Commons page, choose **Create account**. Choose a username and a
   unique password/passphrase of 15–128 characters. Usernames use 3–32 ASCII
   letters, digits or underscores and start with a letter; matching ignores case.
2. Save the displayed recovery code privately, preferably in a password manager.
   It can reset the password and gain access to the inbox. It is shown only once.
3. Use the public rooms and private inbox as usual. **Leave chat** signs out;
   **Sign in** returns to the same account. A new sign-in ends the previous
   session for that account. Ordinary tabs in one browser profile share a cookie.
4. **Account security** checks your current password, lets you set a password,
   and issues a replacement recovery code. Reusing your current password here
   is permitted if you only need to replace the recovery code.
5. If you forget the password, use **Recover account** with the username and
   saved code. This revokes the old session, replaces the password and recovery
   code, then asks you to sign in. Save the replacement code; the old one no
   longer works.
6. In **Account security**, choose **Export my account data** to download a
   retained-data copy, or **Close account** to review permanent closure. These
   are separate actions, each requiring your current password. The export does
   not change your password, replace a recovery code, or close the account.

If you already joined as a guest, choose **Save my account** before leaving or
the eight-hour session expires. That upgrades the current participant and keeps
its inbox and sent messages. Its visible name, including on retained messages,
changes to the account username. Expired/logged-out guests cannot reclaim their
old identity by creating a similarly named account.

A saved account's contact code accepts invitations while that account is signed
out. Invitations still require acceptance before messages are readable. The
24-hour deadline for unopened disappearing messages still applies while offline.

Reloading the page makes no chat API requests automatically. **Resume existing
session** is an explicit reconnect action; it works only while the existing
cookie/session is valid. Otherwise use **Sign in**. Pause/resume continues to
work within a joined session without logging out.

## Export your account data

Choose **Account security → Export my account data**, enter your current
password, and choose **Download account data**. The browser collects the data
with progress feedback and downloads one `fieldforge-commons-my-account.json`
file only when collection and authorization cleanup succeed. Keep that file
private: it contains your own retained message text and profile data.

The export includes:

- Your account username, participant/contact ID, account creation time, chat
  display name and optional chat skill label.
- Your saved profile and private assessment answers, if present, plus your own
  normalized PNG photo. A photo is included whether or not you chose to share it.
- Current outgoing block settings and retained conversation titles you created.
- All of your retained, undeleted public message bodies across rooms, and all
  retained, unredacted **saved** private messages you wrote, including messages
  in conversations you previously left that still exist for other members.
- Metadata for your retained submitted reports: message ID, reason and time.

It excludes other people's message bodies, all open-once bodies, report evidence,
passwords, password/recovery/session hashes, recovery codes, export authorization
tokens, original photo uploads, and unsaved browser drafts. It cannot retrieve
content already withdrawn, expired, or removed by normal retention. Exporting
does not open a private message or mark a delivery read.

This account export has no 1,000-message cutoff. The existing room/inbox export
buttons remain smaller convenience exports; the account export gathers every
eligible retained record using pages of at most 500 records. Each API reply
remains within the portal's existing response limit, and the browser assembles
serialized pages into one download without building a second giant data object.

The file records its scope, initial totals, actual collected counts, and start
and finish times. It is **not a consistent snapshot**: each section has a starting
maximum ID, so new messages are excluded, while withdrawals, report updates or
retention during collection can change later pages. Initial totals can therefore
differ from final counts. Closing or hiding the view, pausing chat, a session
change, or an interrupted request stops collection without a partial download.
Start a new export if collection stops or its five-minute authorization expires.

### Account export API

All routes use the existing authenticated, same-origin JSON request protections
and bind requests to the current participant. No route accepts another account
as a target.

| Route | Exact request fields | Result |
| --- | --- | --- |
| `POST /api/commons/account/export` | `password` | Manifest and a short-lived `export_token` |
| `POST /api/commons/account/export/page` | `export_token`, `section`, `after` | Up to 500 ordered records and an exclusive `next_after` cursor, or `null` when complete |
| `POST /api/commons/account/export/finish` | `export_token` | Revokes the authorization and returns `ok: true` |

The sections are `public_messages`, `private_messages`, `public_reports`, and
`private_reports`. Start each section at integer `after: 0`; use its returned
cursor until `next_after` is `null`. Reports use message IDs as cursors. Each
account has one export authorization, bound to its current session and valid
for five minutes. Starting another export replaces it. A finished, expired,
replaced, or wrong-session authorization returns 410; an ended account session
returns 401. The downloaded file omits the authorization token.

## Close your account

Choose **Account security → Close account** and review the consequences. An
optional **Export my account data first** button lets you obtain a copy before
returning to closure. Enter the current password, type your own username without
the `@` sign, check the confirmation box, and choose **Permanently close account**.
Username confirmation ignores ASCII letter case but must match the signed-in
account; it cannot select a different account to close.

Closure commits these changes together:

- Removes the saved account's password and recovery credentials, profile, photo
  and active export authorization, and revokes its session immediately.
- Withdraws every retained public and private body authored by that account,
  including open-once bodies and messages in conversations it previously left.
- Leaves all private conversations, consumes its pending one-time deliveries,
  clears its outgoing blocks, and replaces its visible participant name with
  **Closed account**.

Other members keep their messages and access to conversations with remaining
eligible members, subject to the existing retention limits. A conversation with
no accepted or invited members is reclaimed, including its retained content.
Shared titles, participant/message references, incoming blocks, reports,
moderation records and invitation receipts can remain under their existing
retention rules. Text other people wrote may still contain the old username or
copies of earlier messages. Closure does not rewrite those words.

The closed account cannot sign in, recover, or be reopened through the owner
console. Its old username is permanently reserved against registration and guest
use using a stored SHA-256 fingerprint; that fingerprint is not an anonymity
guarantee against guessing. A minimal participant reference, closure time and
username fingerprint remain so shared history and safety records stay valid.
The retained reference still counts toward the preview's participant limit.
The label **Closed account** is reserved against guest and profile impersonation.

The sole owner account `CLRYAN86` cannot use self-service closure. The backend
checks both its reserved username and owner configuration before any closure
transaction; removing the console button is only an interface convenience.

`POST /api/commons/account/close` accepts exactly `password`, `username`, and
boolean `confirm: true`, and returns `closed: true` with the session cookie
left unchanged but its old token revoked. It deliberately sends no `Set-Cookie`
header: a delayed closure reply must not erase a newer sign-in from another tab.
A rejected current password returns 403 without closing the account.
The current-password checks for export and closure use the same persistent
credential limits as sign-in and recovery.

**A lost closure reply is uncertain.** Closure may already have committed. The
browser clears the old account's local view and reports that confirmation was
lost; it never automatically repeats the operation. If needed, sign in explicitly
to check whether the account still exists. No retry response can prove success
after its credentials have been deleted. Closing the dialog after submission
does not cancel a transaction that the server already received.

Closure cannot recall screenshots, previous exports, recipient copies, database
backups, filesystem snapshots or data already delivered into memory. It is an
application-level removal operation, not a promise of forensic erasure. Restoring
an older database backup may restore the old account, messages and credentials.

## Recovery and lost replies

There is no email reset service or administrator password-reset bypass. Losing
both the password and recovery code loses access through this interface. A local
operator with access to the database is outside this preview's security boundary.

Creation, password changes, and recovery commit before returning the new code.
If a response is lost, the operation might have succeeded. Try signing in with
the chosen password, then use Account security to issue a fresh recovery code.
The API does not replay a previously issued code. A failed sign-in reply can be
retried; the next successful sign-in rotates the session again.

Password fields are cleared after submission and when the tab is hidden. The
displayed recovery code is cleared when dismissed, when the page leaves, or when
the tab becomes hidden. If it was cleared before you saved it, sign in using your
password and generate a replacement. Unsaved chat drafts are cleared on logout
or an expired/revoked session to avoid carrying them into another identity.

## Implementation and boundaries

- Passwords are salted with 16 random bytes and hashed with Python's OpenSSL
  `hashlib.scrypt`: N=32768, r=8, p=3, 32-byte output, 64 MiB allocation cap.
  The stored encoding includes those parameters. Passwords are not trimmed or
  silently truncated. The work factor follows a documented
  [OWASP scrypt configuration](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
- A recovery code contains 256 cryptographically random bits; the database
  stores only its SHA-256 digest. Successful recovery consumes it atomically,
  replaces it, and revokes the current session. Comparison uses `compare_digest`.
- Session tokens contain 256 random bits, are stored as hashes, and last up to
  eight hours. Sign-in, account creation/upgrade and password changes rotate
  them. There is one current session per participant. Cookies are HttpOnly and
  SameSite=Strict. HTTP is limited to loopback; a public service needs HTTPS and
  Secure cookies.
- All credential operations count toward persistent limits: eight attempts per
  username and sixty total per database per fifteen-minute window. Unknown
  usernames count too. At most two account operations can be in progress per
  server instance. Counters survive restarts; their storage is bounded by the
  global limit. These conservative local limits include successful operations
  and can temporarily prevent legitimate sign-ins. They are not production
  abuse protection.
- Sign-out, recovery, owner password changes and account closure revoke their
  old server sessions without sending a cookie-deletion response. A delayed
  reply therefore cannot erase a newer sign-in in a different tab. An obsolete
  browser cookie grants no access; the next explicit sign-in replaces it.
- During sign-in, wrong passwords and nonexistent usernames return the same credential error;
  both run a password hash. Recovery failures use the same generic response.
  Registration necessarily reports username availability, since names are public.
- No passwords, password hashes or recovery codes appear in chat exports,
  messages or operator reports. Auth responses use the existing no-store headers.
  Inputs require the existing same-origin, JSON, custom-header protections.
- `CLRYAN86`, `King`, administrator/moderator usernames and closed usernames remain reserved.
  Registration cannot assign roles. [Owner setup](COMMONS_OWNER.md) is a separate
  local-terminal action with authenticator verification. No owner credentials
  are embedded in code.
  Skill labels grant no privileges.

Accounts introduced schema version 3; the owner console adds version 4,
profiles add version 5, the [inbox lifecycle update](COMMONS_PRIVATE_MESSAGES.md)
adds version 6, and account export/closure adds version 7. Version **8** adds
separate, default-off consent for
[invitations from directory profiles](COMMONS_PROFILES.md#invite-a-directory-member-to-chat).
Current **version 9** adds [owner announcements](COMMONS_OWNER.md#owner-announcements)
and bounded withdrawn-notice retry metadata.
These upgrades
preserve saved-account data. Version 3 adds accounts and rate-limit counters
to version 1/2 databases.
Saved accounts keep their inbox across expired or revoked sessions. Version 6
retires irrecoverable guest memberships and reclaims conversations only after
their last eligible member leaves; it retains bounded invitation retry records.
Version 7 adds the closed-account references and session-bound export grants;
upgrading does not close existing accounts or issue export authorizations.
Version 8 keeps existing profiles unavailable for directory invitations until
their owners explicitly save that sharing choice. Profile and account exports
include the saved invitation choice; deleting the profile or closing the account
removes it.
Stop the server and back up the database before changing versions. Old binaries
that do not understand the current schema must not be used against the upgraded database.
Restoring a backup may also restore credentials/sessions that had since been
revoked; backup recovery and secret rotation need an operational procedure before
public launch. Do not publish or commit databases or recovery codes.

## Still needed for public launch

Verified email/social identity integration, production administration hardening,
owner succession and recovery operations, compromised-password screening, reviewed
distributed abuse controls, HTTPS deployment, recovery/backup operations, and
security review remain unfinished. Hosting/domains/provider credentials are not
configured. The server deliberately remains at `127.0.0.1` with no public binding
option. Screenshots cannot be reliably prevented; message bodies are not
end-to-end encrypted.

Authentication choices were checked against OWASP's
[authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
and [recovery](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html)
guidance on 2026-10-05. This is implementation guidance, not a security certification.

## Verification

For the earlier account release, on 2026-10-05 the combined
chat/account/profile/portal/connection suite passed
**145 tests and six subtests**, including all **eight Chromium browser tests**.
One existing native Tk handoff test was skipped because there is no graphical
desktop in this environment. Scoped Ruff and JavaScript syntax checks passed.
The built wheel was tested outside the source checkout: account persistence,
recovery, and the packaged account interface passed.

`tests/test_commons_accounts.py` exercises upgrade and database restart, stable
inbox ownership, offline invitations, name reservation, password hashing and
input limits, session/recovery rotation, concurrent recovery, persistent rate
limits, and HTTP consent/origin/cookie protections. Browser tests exercise guest
upgrade with retained private messages, sign-out/sign-in, recovery and password
change, second-browser revocation, explicit reconnect, and a lost sign-in reply.

```sh
python -m pytest -o addopts='' -q tests/test_commons_accounts.py
FIELDFORGE_PORTAL_BROWSER_TESTS=1 python -m pytest -o addopts='' -q tests/test_commons_accounts_browser.py
```

Browser tests require Playwright and Chromium, as described in the chat guide.

## Account lifecycle verification

On 2026-10-05, the combined Commons/account/profile/photo/community/portal suite
passed **388 tests and six subtests**, including **41 Chromium browser tests**,
in 285.91 seconds. One existing native graphical handoff test was skipped because
this environment has no graphical desktop. This update adds **77 lifecycle
cases**: 32 native tests, 32 HTTP tests, and 13 browser cases.

Repository-wide Ruff, JavaScript syntax checks, and whitespace checks passed.
The wheel was installed outside the source checkout and checked under
`python -S`, without optional dependencies, for export, closure, preserved other
members' messages, schema 7 and restart. All 31 packaged online code/asset files
matched the working source bytes. The mobile consequences and confirmation
screens were inspected at 390 pixels wide.

The combined run also exposed a timing assumption in an existing delayed-export
browser regression. It now waits explicitly for response capture before
switching accounts; the five session browser cases and final combined rerun pass.

The lifecycle coverage is in `tests/test_commons_lifecycle.py`,
`tests/test_commons_lifecycle_http.py`, and
`tests/test_commons_lifecycle_browser.py`. The cases exercise:

- Atomic closure and rollback, persistent username reservation, independent
  owner guards, closed-member console behavior, and schema 6-to-7 preservation.
- Old session/password/recovery rejection, credential throttling, logout while
  reauthentication waits, simultaneous closure, and a photo decoder finishing
  after closure.
- Every export section across multiple bounded pages, more than 1,000 public
  and private sent records, retained messages in left conversations, a total
  HTTP export exceeding 8 MiB, and unchanged private read/open state.
- Export grant hashing, five-minute expiry, session binding, replacement and
  explicit finish; exclusion of other people's bodies, open-once bodies and
  credentials from the downloaded file.
- Mobile confirmation, wrong-password and lost-response handling, hiding,
  pausing and cancelling exports, expired grants, and account switches while
  page, finish or closure replies are delayed.

The cross-tab browser regression closes one account, signs a different account
in before the old reply is delivered, and verifies that the newer cookie, draft
and live sending survive. Equivalent HTTP response checks cover sign-out,
recovery and owner password changes. Tests use temporary databases and explicitly
marked TEST passwords/content; no real account is closed by these tests.
