"""Sole-owner moderation for the loopback Commons preview.

Owner provisioning and factor recovery are local-terminal operations, never
HTTP endpoints. Administrative sessions require password plus TOTP. Only
reported private messages may be reviewed; open-once bodies are never returned.
"""

from __future__ import annotations

import hmac
import re
import secrets

from fieldforge.online.accounts import (
    BAD_CREDENTIALS,
    AccountStore,
    _hash_password,
    _password,
    _recovery_hash,
    _username,
    _verify,
)
from fieldforge.online.chat_store import MAX_PARTICIPANTS, ChatError, _digest, _message_id
from fieldforge.online.private_chat import _opaque

OWNER_USERNAME = "clryan86"
OWNER_SECONDS = 15 * 60
REASONS = {"spam", "harassment", "unsafe", "other"}
MAX_AUDIT = 1000


def otp_library():
    try:
        import pyotp
    except ImportError:
        raise ChatError(503, 'Owner MFA requires the optional package: pip install ".[commons]"') from None
    return pyotp


def _reason(value):
    if not isinstance(value, str) or value not in REASONS:
        raise ChatError(400, "Choose a moderation reason.")
    return value


def _totp_counter(secret, code, now, last=-1):
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        raise ChatError(401, BAD_CREDENTIALS)
    totp = otp_library().TOTP(secret)
    current = int(now // 30)
    # Consume the matched step in the same transaction as the authenticated action.
    for counter in (current, current - 1, current + 1):
        if counter > last and hmac.compare_digest(totp.at(counter * 30), code):
            return counter
    raise ChatError(401, "The authenticator code was not accepted or was already used. Wait for a new code.")


class OwnerStore(AccountStore):
    def __init__(self, path, **kwargs):
        super().__init__(path, **kwargs)
        with self._db() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            db.executescript("""
                CREATE TABLE IF NOT EXISTS owner_config (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    participant TEXT NOT NULL UNIQUE REFERENCES accounts(participant),
                    totp_secret TEXT NOT NULL, last_counter INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS owner_grants (
                    token_hash TEXT PRIMARY KEY, expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS participant_controls (
                    participant TEXT PRIMARY KEY REFERENCES participants(id),
                    suspended INTEGER NOT NULL CHECK(suspended IN (0,1)),
                    reason TEXT NOT NULL, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS moderation_resolutions (
                    scope TEXT NOT NULL CHECK(scope IN ('public','private')),
                    message INTEGER NOT NULL, outcome TEXT NOT NULL,
                    reason TEXT NOT NULL, updated REAL NOT NULL, PRIMARY KEY(scope,message)
                );
                CREATE TABLE IF NOT EXISTS owner_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL,
                    target TEXT NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL
                );
            """)
            db.execute(f"PRAGMA user_version={max(4, version)}")

    def _audit(self, db, event, target, reason=""):
        db.execute("INSERT INTO owner_audit(event,target,reason,created) VALUES(?,?,?,?)",
                   (event, target, reason, self.clock()))
        db.execute("DELETE FROM owner_audit WHERE id NOT IN (SELECT id FROM owner_audit ORDER BY id DESC LIMIT ?)", (MAX_AUDIT,))

    def _member(self, db, token):
        member = super()._member(db, token)
        if self._suspended(db, member["id"]):
            raise ChatError(401, "This participant is suspended. Contact the local owner.")
        return member

    @staticmethod
    def _suspended(db, participant):
        return db.execute("SELECT 1 FROM participant_controls WHERE participant=? AND suspended=1", (participant,)).fetchone()

    def _session(self, db, participant, previous_token=None):
        if self._suspended(db, participant):
            raise ChatError(403, "This participant is suspended. Contact the local owner.")
        if db.execute("SELECT 1 FROM owner_config WHERE participant=?", (participant,)).fetchone():
            db.execute("DELETE FROM owner_grants")
        return super()._session(db, participant, previous_token)

    def _contact_available(self, db, contact):
        return not self._suspended(db, contact) and super()._contact_available(db, contact)

    def account_login(self, username, password, token=None):
        if _username(username) == OWNER_USERNAME:
            raise ChatError(403, "Use Owner console to sign in with your password and authenticator.")
        return super().account_login(username, password, token)

    def account_recover(self, username, recovery_code, new_password):
        if _username(username) == OWNER_USERNAME:
            raise ChatError(403, "Owner recovery is available only from the local terminal.")
        return super().account_recover(username, recovery_code, new_password)

    def account_change_password(self, token, password, new_password):
        with self._db() as db:
            member = self._member(db, token)
            if db.execute("SELECT 1 FROM owner_config WHERE participant=?", (member["id"],)).fetchone():
                raise ChatError(403, "Use Owner console to update owner credentials with your authenticator.")
        return super().account_change_password(token, password, new_password)

    def owner_bootstrap(self, password, secret, code):
        """Local CLI only. Caller displays a fresh secret and obtains its first code."""
        _password(password)
        counter = _totp_counter(secret, code, self.clock())
        with self._attempt(OWNER_USERNAME), self._db() as db:
            if db.execute("SELECT 1 FROM owner_config").fetchone():
                raise ChatError(409, "The sole owner is already configured. Setup cannot replace it.")
            if db.execute("SELECT 1 FROM accounts WHERE username=?", (OWNER_USERNAME,)).fetchone():
                raise ChatError(409, "The owner username is already occupied. No account was changed.")
            if db.execute("SELECT COUNT(*) FROM participants").fetchone()[0] >= MAX_PARTICIPANTS:
                raise ChatError(409, "This local preview is full.")
            participant, recovery = secrets.token_hex(12), secrets.token_urlsafe(32)
            db.execute("INSERT INTO participants(id,name,name_key,skill,expires) VALUES(?, 'King', 'king', '', 0)", (participant,))
            db.execute("INSERT INTO accounts VALUES(?,?,?,?,?)",
                       (participant, OWNER_USERNAME, _hash_password(password), _recovery_hash(recovery), self.clock()))
            db.execute("INSERT INTO owner_config VALUES(1,?,?,?)", (participant, secret, counter))
            self._audit(db, "owner_setup", participant)
            return {"username": "CLRYAN86", "recovery_code": recovery}

    def owner_recover(self, recovery_code, new_password, secret, code):
        """Local CLI only. Rotate both credentials; revoke all owner access."""
        _password(new_password)
        with self._attempt(OWNER_USERNAME), self._db() as db:
            row = db.execute("SELECT a.* FROM accounts a JOIN owner_config o ON o.participant=a.participant").fetchone()
            if not row or not hmac.compare_digest(_recovery_hash(recovery_code), row["recovery_hash"]):
                raise ChatError(401, BAD_CREDENTIALS)
            counter = _totp_counter(secret, code, self.clock())
            recovery = secrets.token_urlsafe(32)
            db.execute("UPDATE accounts SET password_hash=?,recovery_hash=? WHERE participant=?",
                       (_hash_password(new_password), _recovery_hash(recovery), row["participant"]))
            db.execute("UPDATE owner_config SET totp_secret=?,last_counter=?", (secret, counter))
            db.execute("UPDATE participants SET token_hash=NULL,expires=0 WHERE id=?", (row["participant"],))
            db.execute("DELETE FROM owner_grants")
            self._audit(db, "owner_recovery", row["participant"])
            return {"username": "CLRYAN86", "recovery_code": recovery}

    def owner_login(self, username, password, code, token=None):
        key = _username(username)
        _password(password)
        with self._attempt(OWNER_USERNAME), self._db() as db:
            row = db.execute("SELECT a.*,o.totp_secret,o.last_counter FROM accounts a "
                             "JOIN owner_config o ON o.participant=a.participant WHERE a.username=?", (key,)).fetchone()
            if not _verify(password, row["password_hash"] if row else None):
                raise ChatError(401, BAD_CREDENTIALS)
            counter = _totp_counter(row["totp_secret"], code, self.clock(), row["last_counter"])
            db.execute("UPDATE owner_config SET last_counter=?", (counter,))
            new_token, viewer = self._session(db, row["participant"], token)
            expires = self.clock() + OWNER_SECONDS
            db.execute("INSERT INTO owner_grants VALUES(?,?)", (_digest(new_token), expires))
            self._audit(db, "owner_signin", row["participant"])
            return new_token, {"viewer": viewer, "owner_expires": expires}

    def _owner(self, db, token):
        member = self._member(db, token)
        grant = db.execute("SELECT g.expires FROM owner_config o JOIN owner_grants g ON g.token_hash=? "
                           "WHERE o.participant=? AND g.expires>?", (_digest(token), member["id"], self.clock())).fetchone()
        if not grant:
            raise ChatError(403, "Owner verification is required. Sign in to the owner console again.")
        return member, grant["expires"]

    def owner_dashboard(self, token):
        with self._db() as db:
            owner, expires = self._owner(db, token)
            self._expire(db)
            return {"owner": self._public(owner), "owner_expires": expires,
                    "accounts": db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],
                    "guests": db.execute("SELECT COUNT(*) FROM participants p WHERE NOT EXISTS "
                                         "(SELECT 1 FROM accounts a WHERE a.participant=p.id)").fetchone()[0],
                    "suspended": db.execute("SELECT COUNT(*) FROM participant_controls WHERE suspended=1").fetchone()[0],
                    "audit": [dict(row) for row in db.execute(
                        "SELECT a.*,COALESCE(p.name,CASE WHEN a.target LIKE 'public:%' THEN 'Public message #'||substr(a.target,8) "
                        "WHEN a.target LIKE 'private:%' THEN 'Private message #'||substr(a.target,9) ELSE a.target END) AS target_label "
                        "FROM owner_audit a LEFT JOIN participants p ON p.id=a.target ORDER BY a.id DESC LIMIT 100")]}

    def owner_members(self, token, query, offset):
        if not isinstance(query, str) or len(query) > 40 or type(offset) is not int or not 0 <= offset <= MAX_PARTICIPANTS:
            raise ChatError(400, "Use a search up to 40 characters and a valid page.")
        with self._db() as db:
            owner, _ = self._owner(db, token)
            query = query.strip().casefold()
            rows = db.execute("SELECT p.id,p.name,a.username,COALESCE(c.suspended,0) AS suspended, "
                              "CASE WHEN p.token_hash IS NOT NULL AND p.expires>? THEN 1 ELSE 0 END AS active_session "
                              "FROM participants p LEFT JOIN accounts a ON a.participant=p.id "
                              "LEFT JOIN participant_controls c ON c.participant=p.id "
                              "WHERE instr(p.name_key,?)>0 OR instr(COALESCE(a.username,''),?)>0 "
                              "ORDER BY p.name_key,p.id LIMIT 50 OFFSET ?", (self.clock(), query, query, offset)).fetchall()
            total = db.execute("SELECT COUNT(*) FROM participants p LEFT JOIN accounts a ON a.participant=p.id "
                               "WHERE instr(p.name_key,?)>0 OR instr(COALESCE(a.username,''),?)>0", (query, query)).fetchone()[0]
            return {"members": [{**dict(row), "owner": row["id"] == owner["id"]} for row in rows], "total": total, "offset": offset}

    def owner_control(self, token, target, action, reason):
        target, reason = _opaque(target), _reason(reason)
        if action not in ("suspend", "restore", "revoke"):
            raise ChatError(400, "Choose suspend, restore, or revoke.")
        with self._db() as db:
            owner, _ = self._owner(db, token)
            if target == owner["id"]:
                raise ChatError(403, "The sole owner cannot be suspended or changed here.")
            if not db.execute("SELECT 1 FROM participants WHERE id=?", (target,)).fetchone():
                raise ChatError(404, "That participant is unavailable.")
            if action in ("suspend", "restore"):
                db.execute("INSERT INTO participant_controls VALUES(?,?,?,?) ON CONFLICT(participant) "
                           "DO UPDATE SET suspended=excluded.suspended,reason=excluded.reason,updated=excluded.updated",
                           (target, int(action == "suspend"), reason, self.clock()))
            if action != "restore":
                db.execute("UPDATE participants SET token_hash=NULL,expires=0 WHERE id=?", (target,))
            self._audit(db, action, target, reason)

    def owner_reports(self, token):
        with self._db() as db:
            self._owner(db, token)
            self._expire(db)
            # Remove resolution metadata once its message is outside bounded retention.
            db.execute("DELETE FROM moderation_resolutions WHERE (scope='public' AND message NOT IN (SELECT id FROM messages)) "
                       "OR (scope='private' AND message NOT IN (SELECT id FROM private_messages))")
            rows = db.execute("""
                SELECT 'public' AS scope,r.message,r.reason,r.created AS created,p.name AS reporter,
                       a.name AS author,m.body,m.room AS location,'saved' AS lifetime
                  FROM reports r JOIN messages m ON m.id=r.message
                  JOIN participants p ON p.id=r.reporter JOIN participants a ON a.id=m.author
                UNION ALL
                SELECT 'private',r.message,r.reason,r.created,p.name,a.name,
                       CASE WHEN m.lifetime='saved' THEN m.body ELSE '' END,'Reported private message',m.lifetime
                  FROM private_reports r JOIN private_messages m ON m.id=r.message
                  JOIN participants p ON p.id=r.reporter JOIN participants a ON a.id=m.author
                ORDER BY 4 DESC LIMIT 200
            """).fetchall()
            resolutions = {(r["scope"], r["message"]): dict(r) for r in db.execute("SELECT * FROM moderation_resolutions")}
            return {"reports": [{**dict(r), "resolution": resolutions.get((r["scope"], r["message"]))} for r in rows],
                    "limit": 200}

    def owner_resolve(self, token, scope, message, action, reason):
        message, reason = _message_id(message), _reason(reason)
        if scope not in ("public", "private") or action not in ("dismiss", "remove"):
            raise ChatError(400, "Choose a reported message and a moderation action.")
        with self._db() as db:
            self._owner(db, token)
            reports, messages = ("reports", "messages") if scope == "public" else ("private_reports", "private_messages")
            if not db.execute(f"SELECT 1 FROM {reports} WHERE message=?", (message,)).fetchone():
                raise ChatError(404, "Only retained reported messages can be reviewed here.")
            previous = db.execute("SELECT outcome FROM moderation_resolutions WHERE scope=? AND message=?", (scope, message)).fetchone()
            if previous and previous["outcome"] == "remove":
                return {"ok": True}  # Dismiss never restores a removed body.
            if action == "remove":
                field = "deleted=1" if scope == "public" else "redacted='moderated'"
                db.execute(f"UPDATE {messages} SET body='',{field} WHERE id=?", (message,))
            db.execute("INSERT INTO moderation_resolutions VALUES(?,?,?,?,?) ON CONFLICT(scope,message) "
                       "DO UPDATE SET outcome=excluded.outcome,reason=excluded.reason,updated=excluded.updated",
                       (scope, message, action, reason, self.clock()))
            self._audit(db, action + "_report", f"{scope}:{message}", reason)

    def owner_lock(self, token):
        with self._db() as db:
            member = self._member(db, token)
            if not db.execute("SELECT 1 FROM owner_config WHERE participant=?", (member["id"],)).fetchone():
                raise ChatError(403, "Owner access required.")
            db.execute("DELETE FROM owner_grants")
            self._audit(db, "owner_lock", member["id"])

    def owner_password(self, token, password, code, new_password):
        _password(password)
        _password(new_password)
        with self._attempt(OWNER_USERNAME), self._db() as db:
            owner, _ = self._owner(db, token)
            row = db.execute("SELECT a.*,o.totp_secret,o.last_counter FROM accounts a JOIN owner_config o "
                             "ON o.participant=a.participant").fetchone()
            if not _verify(password, row["password_hash"]):
                raise ChatError(401, BAD_CREDENTIALS)
            counter = _totp_counter(row["totp_secret"], code, self.clock(), row["last_counter"])
            recovery = secrets.token_urlsafe(32)
            db.execute("UPDATE accounts SET password_hash=?,recovery_hash=? WHERE participant=?",
                       (_hash_password(new_password), _recovery_hash(recovery), owner["id"]))
            db.execute("UPDATE owner_config SET last_counter=?", (counter,))
            db.execute("DELETE FROM owner_grants")
            db.execute("UPDATE participants SET token_hash=NULL,expires=0 WHERE id=?", (owner["id"],))
            self._audit(db, "owner_password", owner["id"])
            return {"recovery_code": recovery}
