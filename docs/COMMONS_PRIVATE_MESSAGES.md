# Private inbox and disappearing messages

This extends the **local** FieldForge Commons preview. It is a working inbox
inside the program, not an email service: it does not send email or connect to
external mail accounts. Launch it with the [existing preview command](COMMONS_CHAT_PREVIEW.md#start-it),
then choose **Private inbox** after joining. [Local accounts](COMMONS_ACCOUNTS.md)
now let you keep the same inbox across sign-outs and server restarts.

![Private group in the browser test](images/commons-private-preview.png)

The screenshot uses test participants. No real community activity is fabricated.

## Start a conversation

1. The recipient opens Private inbox and shares their contact code with you.
   Preview names are unverified; confirm the code with the intended person.
2. Choose **New**, select a one-to-one conversation or a private group, enter a
   subject/group name, and paste the recipient codes. Groups support eight
   participants including the creator.
3. The recipient sees an invitation with its title and participant list. They
   must accept before reading or sending messages. Acceptance makes messages
   sent since the invitation available to them.
4. Use **Saved** for ordinary inbox messages, or select **Open once** before
   sending. Each conversation retains its own unsent draft in the current tab.

Recipients who were never invited cannot list, read, open, post, report, or
withdraw messages in that conversation. Every operation checks membership on
the server. Knowing a thread ID or another person's contact code grants no access.

Members may leave; a left or declined invitation cannot be rejoined in this
preview. Create a new conversation to add members. Blocking either direction
stops new private invitations/messages between those people and consumes their
pending open-once deliveries to one another. In a group, a sender with a blocked
recipient must use a different conversation to continue sending. Other unblocked
members may continue their own conversation. The Community rooms tab retains the
block list and Unblock control.

## Saved versus open-once delivery

| Behavior | Saved | Open once |
|---|---|---|
| Message body appears in conversation history | Yes | Never; history shows a placeholder |
| Recipient action | Open the accepted conversation | Explicitly choose **Open once** and confirm |
| Body can be fetched again | Yes, while retained and still a member | No, even after a failed delivery reply |
| Sender can reread from sent history | Yes | No |
| Personal sent-message export | Included | Excluded |
| Report body available to the local operator | Yes, if retained | No; only reason and message metadata |
| Automatic expiry | By the 200-message conversation retention limit | After opening by all recipients or 24 hours unopened, whichever comes first |

Opening is an atomic server operation: it marks that recipient's delivery as
consumed before returning its body. Simultaneous open requests cannot both
retrieve it. If the reply is lost, the body is not replayed; the recipient may
lose the message without seeing it. The interface explains this before opening.

The browser shows the delivered text in a dialog, then clears it after 30
seconds, on closing the dialog, on leaving the tab, or on pausing/leaving chat.
Each group recipient has a separate one-time delivery. The server keeps a body
only while another original recipient can still open it, up to the 24-hour
deadline. A recipient leaving or being blocked consumes their pending delivery.
Expiry is checked during private API use, at server startup, and by an idle
server sweep once per minute. A stopped server cannot sweep its database until
it starts again. Expired bodies are never returned by the API.

**Screenshots cannot be reliably prevented.** A recipient can use operating
system capture tools, another camera, developer tools, or a modified client to
retain delivered content. Browser clearing is a convenience, not a guarantee
that someone cannot preserve a copy. There are no screenshot-blocking or
screenshot-detection claims in this feature.

The database is not end-to-end encrypted. The local operator can inspect stored
data. Clearing body fields and enabling SQLite secure deletion do not guarantee
erasure from backups, filesystem snapshots, memory, or recipient devices. Thread
titles, participant records, message IDs/times, and delivery state remain after
a body is cleared. Do not put sensitive content in a disappearing message's
subject and expect that subject to disappear.

## Important preview limits

- Guest identities expire within eight hours; logout or expiry loses their inbox
  access. Save the guest as an account before leaving to retain its identity.
  Local accounts sign back in to the same inbox after session expiry or logout.
- The service still binds only to `127.0.0.1`; it is not exposed publicly.
- No public accounts, email recovery, social sign-in, attachments, notifications,
  external email delivery, or end-to-end encryption are implemented.
- Each database supports 200 private conversations, 20 per participant, and 200
  retained messages per conversation. The UI shows the latest 100. A new message
  can age out the oldest message even if it was unread. Personal export contains
  up to 1,000 saved messages sent by the current participant in conversations
  they still belong to.
- Sending is limited to one new message every two seconds across public and
  private conversations. Duplicate retries do not resend retained messages.
- Reports go to the local operator using `--review-reports` or the
  [authenticated owner console](COMMONS_OWNER.md); no staffed
  moderation or emergency response is available. Open-once bodies are never
  retained as report evidence.

Private messaging introduced schema version 2; local accounts add version 3
without removing public room
history or active sessions. Keep a backup of test data before changing versions.
The preview refuses to use an unrelated application database.

## Public launch status

The existing Linux/Caddy deployment examples apply to the map portal; they do
not turn this local-account preview into a public messaging service.
There is still no configured public hostname or public Commons deployment.

The next release work is verified sign-in and email recovery integration,
production abuse/moderation operations, deployment hardening,
HTTPS and secure sessions, backups and recovery testing, and deployment to a
chosen host. Email/social provider configuration and an operator-controlled
domain are not supplied by an OpenAI API account.

The screenshot restriction cannot be promised at public launch either. An
end-to-end encrypted mode would require a maintained protocol/client and a
separate review; this implementation does not build custom cryptography.

## Initial private-message verification, 2026-10-05

The combined chat, private-message, profile, portal and connection suite passed
**113 tests plus six subtests**. One existing Tk desktop handoff test was skipped
because this run has no native graphical display. All **five Chromium browser
tests** ran, including three-browser private group delivery, unauthorized inbox
access, invite acceptance, saved replies/exports, automatic 30-second clearing,
and a lost open response that cannot be replayed.

Storage tests also cover simultaneous open requests, per-recipient consumption,
expiry after restart and during an idle server sweep, invitation/message retry
IDs, blocking, leaving, author-only withdrawal, bounded retention, and the
version-1-to-2 database migration. Ruff and JavaScript syntax checks passed.
The built wheel was checked outside the source checkout: private assets were
present and a private invitation followed by one-time delivery succeeded.
