"""Durable local Commons identities. This is not a public identity provider.

Passwords use the standard-library scrypt implementation; recovery codes carry
256 random bits and are stored only as SHA-256 hashes. Neither is logged or
included in exports. The existing single-session identity rotates on sign-in.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
from contextlib import contextmanager

from fieldforge.online.chat_store import (
    MAX_PARTICIPANTS,
    SESSION_SECONDS,
    ChatError,
    ChatStore,
    _digest,
)
from fieldforge.online.community import CATEGORY_BY_ID
from fieldforge.online.private_chat import PrivateChatStore

AUTH_WINDOW = 15 * 60
AUTH_ACCOUNT_LIMIT = 8
AUTH_GLOBAL_LIMIT = 60
RESERVED = {"admin", "administrator", "moderator", "clryan86", "king", "closed account"}
BAD_CREDENTIALS = "The username or credential was not accepted."


def _username(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{2,31}", value):
        raise ChatError(400, "Use a 3–32 character username: letters, numbers and underscores; start with a letter.")
    return value.lower()


def _password(value):
    if not isinstance(value, str) or not 15 <= len(value) <= 128:
        raise ChatError(400, "Use a password or passphrase of 15–128 characters.")
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError:
        raise ChatError(400, "The password contains an unsupported character.") from None


def _hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    # OWASP's documented 32 MiB configuration, avoiding an extra native dependency.
    derived = hashlib.scrypt(_password(password), salt=bytes.fromhex(salt), n=2**15,
                             r=8, p=3, maxmem=64 * 1024 * 1024, dklen=32)
    return f"scrypt$32768$8$3${salt}${derived.hex()}"


def _verify(password, encoded):
    # Unknown users still perform the same expensive password operation.
    salt = encoded.split("$")[4] if encoded else "00" * 16
    candidate = _hash_password(password, salt)
    return hmac.compare_digest(candidate, encoded or "0" * len(candidate))


def _recovery_hash(code):
    if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", code):
        return "0" * 64
    return hashlib.sha256(code.encode("ascii")).hexdigest()


def _closed_username_hash(username):
    # This reserves a public username without retaining its plaintext. It is
    # not anonymization: a guessed username can still be compared to its hash.
    return hashlib.sha256(username.casefold().encode("utf-8")).hexdigest()


class AccountStore(PrivateChatStore):
    def __init__(self, path, **kwargs):
        super().__init__(path, **kwargs)
        self._auth_slots = threading.BoundedSemaphore(2)
        with self._db() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    participant TEXT PRIMARY KEY REFERENCES participants(id),
                    username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                    recovery_hash TEXT NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_attempts (
                    bucket TEXT PRIMARY KEY, started REAL NOT NULL, attempts INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS closed_accounts (
                    participant TEXT PRIMARY KEY REFERENCES participants(id),
                    username_hash TEXT NOT NULL UNIQUE, closed REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS account_exports (
                    participant TEXT PRIMARY KEY REFERENCES accounts(participant) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE, session_hash TEXT NOT NULL,
                    expires REAL NOT NULL, ceilings TEXT NOT NULL
                );
            """)
            db.execute(f"PRAGMA user_version={max(7, version)}")

    def _member(self, db, token):
        member = db.execute("SELECT p.*,a.username AS account_name FROM participants p "
                            "LEFT JOIN accounts a ON a.participant=p.id "
                            "WHERE p.token_hash=? AND p.expires>?", (_digest(token), self.clock())).fetchone()
        if member is None:
            raise ChatError(401, "Your session ended. Sign in or join as a guest to continue.")
        return member

    @staticmethod
    def _public(member):
        result = ChatStore._public(member)
        account = member["account_name"] if "account_name" in member.keys() else None
        result.update(account=bool(account), username=account,
                      identity="local account; identity unverified" if account else result["identity"])
        return result

    def _name_in_use(self, db, name, now):
        return (db.execute("SELECT 1 FROM accounts WHERE username=?", (name.casefold(),)).fetchone()
                or self._closed_username(db, name)
                or super()._name_in_use(db, name, now))

    @staticmethod
    def _closed_username(db, name):
        return db.execute("SELECT 1 FROM closed_accounts WHERE username_hash=?",
                          (_closed_username_hash(name),)).fetchone()

    def _contact_available(self, db, contact):
        return (db.execute("SELECT 1 FROM accounts WHERE participant=?", (contact,)).fetchone()
                or super()._contact_available(db, contact))

    @contextmanager
    def _attempt(self, username):
        if not self._auth_slots.acquire(blocking=False):
            raise ChatError(429, "Account service is busy. Wait a moment and try again.")
        try:
            # Commit counters separately: rejecting a credential must not roll them back.
            now = self.clock()
            with self._db() as db:
                db.execute("DELETE FROM auth_attempts WHERE started<=?", (now - AUTH_WINDOW,))
                for bucket, limit in (("global", AUTH_GLOBAL_LIMIT), ("user:" + username, AUTH_ACCOUNT_LIMIT)):
                    row = db.execute("SELECT attempts FROM auth_attempts WHERE bucket=?", (bucket,)).fetchone()
                    if row and row[0] >= limit:
                        raise ChatError(429, "Too many account attempts. Wait up to 15 minutes before trying again.")
                for bucket in ("global", "user:" + username):
                    db.execute("INSERT INTO auth_attempts VALUES(?,?,1) ON CONFLICT(bucket) "
                               "DO UPDATE SET attempts=attempts+1", (bucket, now))
            yield
        finally:
            self._auth_slots.release()

    def _session(self, db, participant, previous_token=None):
        if previous_token:
            try:
                previous = self._member(db, previous_token)
            except ChatError:
                pass
            else:
                db.execute("UPDATE participants SET token_hash=NULL,expires=0 WHERE id=?", (previous["id"],))
        token = secrets.token_urlsafe(32)
        db.execute("UPDATE participants SET token_hash=?,expires=? WHERE id=?",
                   (_digest(token), self.clock() + SESSION_SECONDS, participant))
        return token, self._public(self._member(db, token))

    def account_register(self, username, password, skill, token=None):
        key = _username(username)
        _password(password)
        if key in RESERVED:
            raise ChatError(400, "That username is reserved. Choose another username.")
        if not isinstance(skill, str) or skill and skill not in CATEGORY_BY_ID:
            raise ChatError(400, "Choose a supported skill or leave it blank.")
        with self._attempt(key), self._db() as db:
            member = None
            if token:
                try:
                    member = self._member(db, token)
                except ChatError:
                    pass
            if member and member["account_name"]:
                raise ChatError(409, "This session already has an account. Sign out before creating another.")
            if (db.execute("SELECT 1 FROM accounts WHERE username=?", (key,)).fetchone()
                    or self._closed_username(db, key)
                    or db.execute("SELECT 1 FROM participants WHERE name_key=? AND expires>? "
                                  "AND token_hash IS NOT NULL AND id!=?",
                                  (key, self.clock(), member["id"] if member else "")).fetchone()):
                raise ChatError(409, "That username is unavailable. Choose another username.")
            if not member and db.execute("SELECT COUNT(*) FROM participants").fetchone()[0] >= MAX_PARTICIPANTS:
                raise ChatError(409, "This local preview is full.")
            encoded = _hash_password(password)
            code = secrets.token_urlsafe(32)
            participant = member["id"] if member else secrets.token_hex(12)
            if member:
                db.execute("UPDATE participants SET name=?,name_key=?,skill=? WHERE id=?",
                           (username, key, skill, participant))
            else:
                db.execute("INSERT INTO participants(id,name,name_key,skill,expires) VALUES(?,?,?,?,0)",
                           (participant, username, key, skill))
            db.execute("INSERT INTO accounts VALUES(?,?,?,?,?)",
                       (participant, key, encoded, _recovery_hash(code), self.clock()))
            new_token, viewer = self._session(db, participant)
            return new_token, {"viewer": viewer, "recovery_code": code}

    def account_login(self, username, password, token=None):
        key = _username(username)
        _password(password)
        with self._attempt(key), self._db() as db:
            row = db.execute("SELECT * FROM accounts WHERE username=?", (key,)).fetchone()
            if not _verify(password, row["password_hash"] if row else None):
                raise ChatError(401, BAD_CREDENTIALS)
            new_token, viewer = self._session(db, row["participant"], token)
            return new_token, {"viewer": viewer}

    def account_resume(self, token):
        with self._db() as db:
            return {"viewer": self._public(self._member(db, token))}

    def account_recover(self, username, recovery_code, new_password):
        key = _username(username)
        _password(new_password)
        with self._attempt(key), self._db() as db:
            row = db.execute("SELECT * FROM accounts WHERE username=?", (key,)).fetchone()
            accepted = hmac.compare_digest(_recovery_hash(recovery_code), row["recovery_hash"] if row else "f" * 64)
            if not row or not accepted:
                raise ChatError(401, BAD_CREDENTIALS)
            encoded = _hash_password(new_password)
            code = secrets.token_urlsafe(32)
            db.execute("UPDATE accounts SET password_hash=?,recovery_hash=? WHERE participant=?",
                       (encoded, _recovery_hash(code), row["participant"]))
            db.execute("UPDATE participants SET token_hash=NULL,expires=0 WHERE id=?", (row["participant"],))
            # Recovery does not silently sign in. It revokes the old session and code.
            return {"recovery_code": code}

    def account_change_password(self, token, password, new_password):
        _password(password)
        _password(new_password)
        with self._db() as db:
            member = self._member(db, token)
            if not member["account_name"]:
                raise ChatError(403, "Create a local account first.")
            key = member["account_name"]
        with self._attempt(key), self._db() as db:
            member = self._member(db, token)  # Recheck after waiting for the limiter.
            row = db.execute("SELECT * FROM accounts WHERE participant=?", (member["id"],)).fetchone()
            if not _verify(password, row["password_hash"]):
                raise ChatError(401, BAD_CREDENTIALS)
            code = secrets.token_urlsafe(32)
            db.execute("UPDATE accounts SET password_hash=?,recovery_hash=? WHERE participant=?",
                       (_hash_password(new_password), _recovery_hash(code), member["id"]))
            new_token, viewer = self._session(db, member["id"])
            return new_token, {"viewer": viewer, "recovery_code": code}
