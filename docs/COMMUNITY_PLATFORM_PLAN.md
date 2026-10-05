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

Profile pictures are optional. The eventual upload handler must accept only
bounded raster files, decode and re-encode them, remove metadata such as EXIF
location, generate an opaque asset ID, and reject SVG/HTML and oversized input.
Pictures, email addresses, real names, and questionnaire answers stay private
unless the member chooses otherwise.

## Community areas and resources

The web experience should connect **Community**, **Maps**, **Knowledge Library**,
**Preparedness**, and **Resources** with a consistent navigation bar. Community
rooms can be grouped by member-selected work area. Include member blocking,
reporting, moderation, admin announcements, and deletion/export controls before
opening rooms to the public.

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

Before enabling registration, test account creation and verification, provider
login, secure account linking, picture upload limits, the single-admin bootstrap,
MFA, admin recovery, profile deletion, export, moderation, session revocation,
backup restoration, and offline desktop behavior. Public launch remains a
separate go/no-go after privacy, rights, hosting, and security review.
