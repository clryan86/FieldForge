"""Explicit account export and terminal self-service closure for local Commons.

Exports use bounded pages and a short-lived, session-bound authorization. A
closed account cannot sign in, recover, or reacquire its old participant ID.
Shared references remain as a generic label; this is not backup erasure.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from contextlib import contextmanager

from fieldforge.online.accounts import _closed_username_hash, _password, _username, _verify
from fieldforge.online.chat_store import ChatError, _digest
from fieldforge.online.owner import OWNER_USERNAME
from fieldforge.online.profiles import PROFILE_FIELDS, ProfileStore

EXPORT_PAGE_SIZE = 500
EXPORT_SECONDS = 5 * 60
EXPORT_SECTIONS = {
    "public_messages": ("messages", "id", "author", "deleted=0", "id,room,body,created"),
    "private_messages": ("private_messages", "id", "author", "lifetime='saved' AND redacted=''",
                         "id,thread,body,created,lifetime"),
    "public_reports": ("reports", "message", "reporter", "1=1", "message,reason,created"),
    "private_reports": ("private_reports", "message", "reporter", "1=1", "message,reason,created"),
}


def _export_hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise ChatError(400, "Start an account export to obtain a valid export reference.")
    return hashlib.sha256(value.encode("ascii")).hexdigest()


class AccountLifecycleStore(ProfileStore):
    @staticmethod
    def _saved_account(db, member):
        row = db.execute("SELECT * FROM accounts WHERE participant=?", (member["id"],)).fetchone()
        if row is None:
            raise ChatError(403, "Save your guest as a local account first.")
        return row

    @staticmethod
    def _can_close(db, member, account):
        if account["username"] == OWNER_USERNAME or db.execute(
                "SELECT 1 FROM owner_config WHERE participant=?", (member["id"],)).fetchone():
            raise ChatError(403, "The sole owner account cannot be closed here. Owner access must remain available.")

    @contextmanager
    def _reauthenticate(self, token, password, *, closing=False):
        _password(password)
        with self._db() as db:
            member = self._member(db, token)
            account = self._saved_account(db, member)
            if closing:
                self._can_close(db, member, account)
            key = account["username"]
        with self._attempt(key), self._db() as db:
            # A session rotation, closure or suspension while waiting invalidates
            # the operation before any export or account mutation can occur.
            member = self._member(db, token)
            account = self._saved_account(db, member)
            if closing:
                self._can_close(db, member, account)
            if not _verify(password, account["password_hash"]):
                raise ChatError(403, "The current password was not accepted. Your account has not changed.")
            yield db, member, account

    def account_export(self, token, password):
        with self._reauthenticate(token, password) as (db, member, account):
            now = self.clock()
            totals, ceilings = {}, {}
            for section, (table, identifier, author, where, _) in EXPORT_SECTIONS.items():
                row = db.execute(f"SELECT COUNT(*),COALESCE(MAX({identifier}),0) FROM {table} "
                                 f"WHERE {author}=? AND {where}", (member["id"],)).fetchone()
                totals[section], ceilings[section] = row
            row = self._row(db, member)
            profile, photo = None, None
            if row is not None and row["saved"]:
                saved = self._profile(member, row)
                profile = {key: saved[key] for key in sorted(PROFILE_FIELDS)}
                if row["photo_png"] is not None:
                    photo = {"mime_type": "image/png", "encoded": base64.b64encode(row["photo_png"]).decode("ascii")}
            manifest = {
                "format": "fieldforge-commons-account", "version": 1, "started_at": now,
                "scope": ("Your account, saved profile and normalized photo, current outgoing blocks, "
                          "retained conversation titles you created, retained undeleted public messages you wrote, "
                          "retained saved private messages you wrote including conversations you left, and reports "
                          "you submitted. Excludes all open-once bodies, other people's message bodies, credentials, "
                          "and content already removed by withdrawal or retention. Records are collected in pages; "
                          "concurrent changes can affect later pages."),
                "account": {"participant": member["id"], "username": account["username"],
                            "display_name": member["name"], "skill": member["skill"], "created": account["created"]},
                "profile": profile, "photo": photo,
                "conversations": [dict(row) for row in db.execute(
                    "SELECT t.id,t.title,t.kind,t.created,m.status FROM private_threads t "
                    "JOIN private_members m ON m.thread=t.id AND m.participant=t.owner "
                    "WHERE t.owner=? ORDER BY t.created,t.id", (member["id"],))],
                "blocks": [dict(row) for row in db.execute(
                    "SELECT b.target,p.name FROM blocks b JOIN participants p ON p.id=b.target "
                    "WHERE b.viewer=? ORDER BY b.target", (member["id"],))],
                "totals": totals, "page_size": EXPORT_PAGE_SIZE, "consistent_snapshot": False,
            }
            reference = secrets.token_urlsafe(32)
            db.execute("DELETE FROM account_exports WHERE expires<=?", (now,))
            db.execute("INSERT INTO account_exports VALUES(?,?,?,?,?) ON CONFLICT(participant) DO UPDATE SET "
                       "token_hash=excluded.token_hash,session_hash=excluded.session_hash,"
                       "expires=excluded.expires,ceilings=excluded.ceilings",
                       (member["id"], _export_hash(reference), _digest(token), now + EXPORT_SECONDS, json.dumps(ceilings)))
            return {"export_token": reference, "manifest": manifest}

    def _export_access(self, db, token, export_token):
        member = self._member(db, token)
        self._saved_account(db, member)
        digest = _export_hash(export_token)
        grant = db.execute("SELECT * FROM account_exports WHERE participant=?", (member["id"],)).fetchone()
        if (grant is None or grant["expires"] <= self.clock()
                or not hmac.compare_digest(digest, grant["token_hash"])
                or not hmac.compare_digest(_digest(token), grant["session_hash"])):
            raise ChatError(410, "This export expired or was replaced. Start a new account export.")
        return member, grant

    def account_export_page(self, token, export_token, section, after):
        if not isinstance(section, str) or section not in EXPORT_SECTIONS:
            raise ChatError(400, "Choose a supported account export section.")
        if type(after) is not int or not 0 <= after < 2**63:
            raise ChatError(400, "Choose a valid account export position.")
        with self._db() as db:
            member, grant = self._export_access(db, token, export_token)
            table, identifier, author, where, columns = EXPORT_SECTIONS[section]
            ceiling = json.loads(grant["ceilings"])[section]
            rows = db.execute(f"SELECT {columns} FROM {table} WHERE {author}=? AND {where} "
                              f"AND {identifier}>? AND {identifier}<=? ORDER BY {identifier} LIMIT ?",
                              (member["id"], after, ceiling, EXPORT_PAGE_SIZE + 1)).fetchall()
            more = len(rows) > EXPORT_PAGE_SIZE
            rows = rows[:EXPORT_PAGE_SIZE]
            return {"section": section, "records": [dict(row) for row in rows],
                    "next_after": rows[-1][identifier] if more else None}

    def account_export_finish(self, token, export_token):
        with self._db() as db:
            member, _ = self._export_access(db, token, export_token)
            db.execute("DELETE FROM account_exports WHERE participant=?", (member["id"],))
            return {"ok": True}

    def account_close(self, token, password, username, confirm):
        if confirm is not True:
            raise ChatError(400, "Confirm that you want to close this account permanently.")
        key = _username(username)
        with self._reauthenticate(token, password, closing=True) as (db, member, account):
            if key != account["username"]:
                raise ChatError(400, "Type your own account username to confirm closure.")
            now, participant = self.clock(), member["id"]
            db.execute("INSERT INTO closed_accounts VALUES(?,?,?)", (participant, _closed_username_hash(key), now))
            db.execute("UPDATE participants SET name='Closed account',name_key=?,skill='',token_hash=NULL,"
                       "expires=0,last_sent=0 WHERE id=?", ("closed:" + participant, participant))
            db.execute("UPDATE messages SET body='',deleted=1 WHERE author=?", (participant,))
            db.execute("UPDATE private_messages SET body='',redacted='deleted' WHERE author=?", (participant,))
            db.execute("UPDATE private_members SET status='left' WHERE participant=?", (participant,))
            db.execute("UPDATE private_deliveries SET opened=COALESCE(opened,?) WHERE recipient=?", (now, participant))
            db.execute("DELETE FROM blocks WHERE viewer=?", (participant,))
            db.execute("DELETE FROM auth_attempts WHERE bucket=?", ("user:" + key,))
            # Profile/photo and active export authorization are foreign-key
            # children of the account; retained shared references point to the
            # generic participant tombstone rather than to credentials.
            db.execute("DELETE FROM accounts WHERE participant=?", (participant,))
            self._expire(db)
            self._audit(db, "account_closed", participant)
            return {"closed": True}
