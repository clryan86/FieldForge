# FieldForge Commons: account and community plan

FieldForge Commons is the opt-in online community connected to the FieldForge
offline program. The desktop library, maps, and saved household data remain
usable without a Commons account. Joining, publishing a profile, and showing
skill categories each require separate user choices.

## Decisions

- Use **FieldForge Commons** as the working name. It describes shared practical
  knowledge without the militant tone of “The Resistance.”
- Keep the existing green and warm neutral portal palette. Use plain, calm
  preparedness language and readable category names.
- The sole owner account is `CLRYAN86`; no public registration flow can assign
  owner or administrator privileges. A public profile display name such as
  “King” is separate from the account username and administrative role.
- Skill tags are **self-reported** by default. “MED” is a text label rather than
  the Red Cross emblem. No questionnaire result is a medical, trade, or safety
  credential. Any later manual verification needs a defined reviewer, scope,
  date, and renewal policy.
- Directory presence is opt-in. A private member can use the online service
  without publishing a profile, photo, skills, or availability.

The shared profile/questionnaire validator is in
`fieldforge/online/community.py`. It defines stable skill category IDs, bounded
answers, optional directory visibility, server-issued picture IDs, and
self-reported badge wording. It is a data contract, not an account server.

## Sign-in and account creation

The requirements in this section concern the future public service. The working
local username/password accounts, owner MFA, export, and closure are documented
in the [account guide](COMMONS_ACCOUNTS.md) and [owner guide](COMMONS_OWNER.md).

Support email-based sign-in and provider integrations through separately
configured OAuth 2.0 / OpenID Connect clients. “All social accounts” is not one
integration: each provider needs its own app registration, callback URL, terms,
and current API support. Start with email plus a short, reviewed provider list;
add providers only after their official sign-in flow and account recovery are
tested.

Never put a password, OAuth client secret, recovery token, or signing key in
source code, browser JavaScript, the desktop application, or a public example
configuration. The password shared in chat must not be reused; rotate it before
any administrator account is created. Bootstrap the one owner from deployment
secrets, store only an Argon2id password hash (or an explicitly reviewed
platform identity-provider credential), require MFA, and provide a forced
first-login password change. Admin recovery must be tested before launch.

Link a social identity only after the user proves control of both the existing
account and the new provider. Matching email addresses alone do not authorize
account linking. Email verification, rate limits, login throttling, session
revocation, CSRF defenses, secure cookies, and abuse monitoring are release
requirements.

## Profile and onboarding

The optional questionnaire asks which areas a member wants to contribute to,
how they describe their experience, and how they prefer to help. It recommends
up to five categories that the member can edit or remove. It does not assign a
person to a job, collect home addresses, infer availability, or test clinical
competence. Initial categories are medical/first aid, food/farming, construction,
water/sanitation, power, machinery, logistics, communications, education,
navigation, community safety, and research/documentation.

Profile pictures are optional. A public-service upload handler must accept only
bounded raster files, decode and re-encode them, remove metadata such as EXIF
location, generate an opaque asset ID, and reject SVG/HTML and oversized input.
Pictures, email addresses, real names, and questionnaire answers stay private
unless the member chooses otherwise.

### Working in the local preview

The [profile editor and local directory](COMMONS_PROFILES.md) now implement this
profile/photo portion for saved local accounts. Profiles default to private.
Members separately choose directory presence, sharing selected interests/ways
to help, and sharing a photo. Experience answers remain private, including their
relative ranking. The directory shows the account username beside the chosen
display name and does not publish private contact codes.

Authenticated uploads normalize bounded PNG/JPEG/WebP files into metadata-free
PNG thumbnails. Each replacement begins private, invalidates its old image ID,
and requires a fresh sharing choice. Blocks in either direction and participant
suspension prevent future directory/photo access. Profile export and deletion
are implemented. Deleting only a profile keeps the account, credentials, inbox,
messages, and blocks; whole-account closure is a separate explicit action.

The shared-tab session guard binds an established browser action to its displayed
participant, clears the old identity after a cookie changes, and rejects late
replies from earlier sessions. Public hosting and verified identity integrations
remain unconfigured.

### Private inbox lifecycle

The private inbox now pages through retained messages with **Older messages**
and **Back to latest**. Each page rechecks membership, blocking, withdrawal and
open-once state, and only returned saved messages receive read receipts.

Declined and left memberships free the participant's conversation slot.
Conversations and their content remain available to any remaining member and
are reclaimed only when no accepted or invited member can return. Expired or
logged-out guests are retired; saved accounts keep their inbox while signed out.
Persistent recipient-weighted daily invitation limits, a per-contact cooldown,
and bounded closed-conversation retry receipts prevent cleanup from bypassing
the local invitation controls. See [private messaging](COMMONS_PRIVATE_MESSAGES.md)
for exact limits and schema version 6 upgrade behavior.

**Search saved messages** now finds literal text across currently accepted
private conversations, with an optional current-conversation filter. It returns
20 matches per page after checking membership, intended delivery, blocking and
withdrawal. Open-once bodies are excluded, and searching leaves read receipts
unchanged. Results can open the original retained history page; the fresh read
rechecks access and highlights the message if it is still available. Queries and
results clear when the search closes, the tab hides, chat pauses or the identity
changes. This increment uses the existing version-8 schema and requires no
search service or index.

### Local account export and closure

Saved members can use **Account security → Export my account data**, with their
current password, to collect retained account details, profile answers and the
normalized photo, their own public and saved private messages, conversation
titles they created, outgoing blocks, and submitted report metadata. Private
sent-message records include retained messages from conversations already left.
Credentials, session secrets, other people's message bodies, and every open-once
body are excluded. Export does not mark messages read or consume open-once
deliveries.

The browser assembles the download from pages of at most 500 records, using a
five-minute authorization tied to the account's current session. This permits a
complete retained export beyond the older 1,000-message exports without one
oversized response. Records are collected across requests, so withdrawal and
retention can affect later pages. New records above
the starting ID limits are excluded. Exporting is optional and does not close
the account.

**Close account** requires the saved member's current password, typed username,
and explicit confirmation. It removes credentials, recovery access, profile and
normalized photo; revokes access; leaves all private conversations; and withdraws
all retained authored public and private message bodies, including messages in
conversations already left. Late profile decoding or old session requests cannot
restore the removed data. Closure revokes the old session on the server without
overwriting a newer account's cookie when a delayed reply arrives. The sole owner
is protected by checks on both the reserved owner username and the configured
owner participant.

Other people's messages, shared titles and conversation metadata, incoming
blocks, and retained report, moderation/audit, and invitation records can remain.
A generic **Closed account** participant record keeps shared references intact,
and a stored username hash permanently reserves the former username. The owner
console identifies and counts closed records separately and cannot restore their
access. Previously viewed copies, downloads, and backups cannot be recalled.

The current Commons schema is **version 9**. The profile additions in version
**5** and invitation lifecycle in version **6** remain part of the supported
upgrade path, along with account export/closure in version **7**. Version **8**
adds a separate invitation choice to profiles, off by default. Saved members
can invite opted-in directory members to direct conversations using their opaque
profile IDs, followed by the normal inbox acceptance flow. Directory and
contact-code invitations share recipient limits, blocking, capacity, and retry
records. The server rechecks current profile visibility and consent when creating
an invitation. Existing accounts and owner configuration are preserved; closure
occurs only through its explicit authenticated action. See the
[account guide](COMMONS_ACCOUNTS.md) for the full scope and migration details.
Version **9** adds bounded owner announcements and withdrawn-notice retry
records. It preserves existing account, owner, profile, and conversation state
under the established retention rules.

## Community areas and resources

The web experience should connect **Community**, **Maps**, **Knowledge Library**,
**Preparedness**, and **Resources** with a consistent navigation bar. Community
rooms can be grouped by member-selected work area. Include member blocking,
reporting, moderation, admin announcements, and deletion/export controls before
opening rooms to the public.

The local preview now implements owner announcements: a current MFA-verified
owner session can publish up to five active plain-text notices or withdraw
them. Connected members, including guests, see these service notices above both
rooms and the private inbox. Publication retries are checked against retained
request records, withdrawal clears notice text, and the bounded owner audit
records the action without the title or body. The server retains withdrawn
retry metadata for seven days, up to 1,000 total announcement records. No push
notifications, delivery receipts, scheduling, or public hosting are implied.
See [owner announcements](COMMONS_OWNER.md#owner-announcements).

Resources should use reviewed topic pages for medical supplies, food and water
storage, communications, tools, MREs, and military-surplus equipment. External
links need a source, review date, region, disclosure of affiliate relationships,
and a reminder to check current laws and product compatibility. Do not imply
that FieldForge sells or endorses an item without a real agreement.

Do not build custom cryptography for private messages. The first release should
use ordinary TLS-protected messages with clear privacy limits and moderation
controls. Add end-to-end encrypted short messages only through a maintained,
independently reviewed protocol or service, with a threat model, key recovery
plan, abuse controls, and expert review. Until then, label private messaging as
not end-to-end encrypted; do not call the platform “secure” without a security
assessment.

## Integration and launch gates

The current map portal is a self-hosted map/search service with no account
system. Commons needs a separately reviewed identity/profile service or an
established identity provider, its own database and migrations, email delivery,
public HTTPS hosting, backups, moderation workflow, privacy/terms documents,
and an incident-response owner. Keep community data out of local FieldForge
backups unless a user explicitly exports it.

Before enabling public registration, test account creation and verification,
provider login, secure account linking, picture upload limits, the single-admin
bootstrap, MFA, admin recovery, profile deletion, account export and closure, shared-data
retention, moderation, session revocation, backup restoration, and offline desktop
behavior. Public launch remains a separate go/no-go after privacy, rights,
hosting, and security review.
