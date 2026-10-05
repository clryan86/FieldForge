"""Invitation-only private threads for the local Commons preview.

View-once delivery is consumed atomically before responding. The server never
replays its body, even when the network reply is lost. This is access control,
not end-to-end encryption or protection from screenshots or database backups.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets

from fieldforge.online.chat_store import (
    MAX_MESSAGE_BYTES,
    MAX_MESSAGE_CHARS,
    ChatError,
    ChatStore,
    _message_id,
    _text,
)

MAX_THREADS = 200
MAX_MEMBER_THREADS = 20
MAX_GROUP_MEMBERS = 8
MAX_THREAD_MESSAGES = 200
VIEW_ONCE_SECONDS = 24 * 60 * 60


def _opaque(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{24}", value):
        raise ChatError(400, "Use the complete conversation or contact code.")
    return value


def _retry_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9-]{32,36}", value):
        raise ChatError(400, "This request needs a valid retry ID.")
    return value


def _blocked(db, first, second):
    return db.execute("SELECT 1 FROM blocks WHERE (viewer=? AND target=?) OR (viewer=? AND target=?)",
                      (first, second, second, first)).fetchone() is not None


class PrivateChatStore(ChatStore):
    def __init__(self, path, **kwargs):
        super().__init__(path, **kwargs)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS private_threads (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL,
                    owner TEXT NOT NULL REFERENCES participants(id), created REAL NOT NULL,
                    request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    UNIQUE(owner, request_id)
                );
                CREATE TABLE IF NOT EXISTS private_members (
                    thread TEXT NOT NULL REFERENCES private_threads(id) ON DELETE CASCADE,
                    participant TEXT NOT NULL REFERENCES participants(id), status TEXT NOT NULL,
                    PRIMARY KEY(thread,participant)
                );
                CREATE TABLE IF NOT EXISTS private_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread TEXT NOT NULL REFERENCES private_threads(id) ON DELETE CASCADE,
                    author TEXT NOT NULL REFERENCES participants(id), body TEXT NOT NULL,
                    lifetime TEXT NOT NULL, created REAL NOT NULL, expires REAL,
                    redacted TEXT NOT NULL DEFAULT '', request_id TEXT NOT NULL,
                    UNIQUE(author,request_id)
                );
                CREATE INDEX IF NOT EXISTS private_thread_messages ON private_messages(thread,id);
                CREATE TABLE IF NOT EXISTS private_deliveries (
                    message INTEGER NOT NULL REFERENCES private_messages(id) ON DELETE CASCADE,
                    recipient TEXT NOT NULL REFERENCES participants(id), opened REAL,
                    PRIMARY KEY(message,recipient)
                );
                CREATE TABLE IF NOT EXISTS private_reports (
                    message INTEGER NOT NULL REFERENCES private_messages(id) ON DELETE CASCADE,
                    reporter TEXT NOT NULL REFERENCES participants(id), reason TEXT NOT NULL,
                    created REAL NOT NULL, PRIMARY KEY(message,reporter)
                );
                PRAGMA user_version=2;
            """)
            self._expire(db)

    def _expire(self, db):
        db.execute("UPDATE private_messages SET body='',redacted='expired' "
                   "WHERE lifetime='view_once' AND redacted='' AND expires<=?", (self.clock(),))
        db.execute("UPDATE private_messages SET body='',redacted='opened' "
                   "WHERE lifetime='view_once' AND redacted='' AND NOT EXISTS "
                   "(SELECT 1 FROM private_deliveries d WHERE d.message=private_messages.id AND d.opened IS NULL)")

    def expire_private_messages(self):
        with self._db() as db:
            self._expire(db)

    def _access(self, db, token, thread, *, invitation=False):
        thread = _opaque(thread)
        member = self._member(db, token)
        row = db.execute("SELECT t.*,m.status FROM private_threads t JOIN private_members m "
                         "ON m.thread=t.id WHERE t.id=? AND m.participant=?",
                         (thread, member["id"])).fetchone()
        if row is None or row["status"] not in (("accepted", "invited") if invitation else ("accepted",)):
            raise ChatError(404, "That private conversation is not available to this session.")
        return member, row

    def _meta(self, db, thread, viewer):
        participants = [dict(row) for row in db.execute(
            "SELECT p.id,p.name,m.status FROM private_members m JOIN participants p ON p.id=m.participant "
            "WHERE m.thread=? ORDER BY p.name", (thread["id"],))]
        unread = db.execute("SELECT COUNT(*) FROM private_deliveries d JOIN private_messages m ON m.id=d.message "
                            "WHERE m.thread=? AND d.recipient=? AND d.opened IS NULL AND m.redacted='' "
                            "AND NOT EXISTS (SELECT 1 FROM blocks b WHERE (b.viewer=? AND b.target=m.author) "
                            "OR (b.target=? AND b.viewer=m.author))",
                            (thread["id"], viewer, viewer, viewer)).fetchone()[0]
        return {"id": thread["id"], "title": thread["title"], "kind": thread["kind"],
                "owner": thread["owner"], "status": thread["status"], "created": thread["created"],
                "participants": participants, "unread": unread}

    def private_inbox(self, token):
        with self._db() as db:
            member = self._member(db, token)
            self._expire(db)
            rows = db.execute("SELECT t.*,m.status FROM private_threads t JOIN private_members m ON m.thread=t.id "
                              "WHERE m.participant=? AND m.status IN ('accepted','invited') ORDER BY t.created DESC,t.id",
                              (member["id"],)).fetchall()
            return {"contact_code": member["id"], "threads": [self._meta(db, row, member["id"]) for row in rows]}

    def private_create(self, token, title, kind, contacts, request_id):
        title = _text(title, 100)
        request_id = _retry_id(request_id)
        if not isinstance(kind, str) or kind not in ("direct", "group"):
            raise ChatError(400, "Choose a direct conversation or a private group.")
        if (not isinstance(contacts, list) or not 1 <= len(contacts) < MAX_GROUP_MEMBERS
                or kind == "direct" and len(contacts) != 1):
            raise ChatError(400, "Direct conversations need one contact; groups support up to seven other contacts.")
        contacts = [_opaque(contact) for contact in contacts]
        if len(set(contacts)) != len(contacts):
            raise ChatError(400, "Enter each contact code once.")
        fingerprint = hashlib.sha256(json.dumps([title, kind, sorted(contacts)]).encode()).hexdigest()
        with self._db() as db:
            member = self._member(db, token)
            previous = db.execute("SELECT id,fingerprint FROM private_threads WHERE owner=? AND request_id=?",
                                  (member["id"], request_id)).fetchone()
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise ChatError(409, "That retry ID belongs to another invitation.")
                return {"thread": previous["id"], "duplicate": True}
            if member["id"] in contacts:
                raise ChatError(400, "Enter another participant's contact code.")
            for contact in contacts:
                if (not db.execute("SELECT 1 FROM participants WHERE id=? AND token_hash IS NOT NULL AND expires>?",
                                   (contact, self.clock())).fetchone() or _blocked(db, member["id"], contact)):
                    raise ChatError(404, "A selected contact is unavailable for a private invitation.")
            if db.execute("SELECT COUNT(*) FROM private_threads").fetchone()[0] >= MAX_THREADS:
                raise ChatError(409, "This local preview has reached its conversation limit.")
            for contact in [member["id"], *contacts]:
                if db.execute("SELECT COUNT(*) FROM private_members WHERE participant=?",
                              (contact,)).fetchone()[0] >= MAX_MEMBER_THREADS:
                    raise ChatError(409, "A participant has reached the preview's conversation limit.")
            thread = secrets.token_hex(12)
            db.execute("INSERT INTO private_threads VALUES(?,?,?,?,?,?,?)",
                       (thread, title, kind, member["id"], self.clock(), request_id, fingerprint))
            db.executemany("INSERT INTO private_members VALUES(?,?,?)",
                           [(thread, member["id"], "accepted"), *[(thread, contact, "invited") for contact in contacts]])
            return {"thread": thread, "duplicate": False}

    def private_accept(self, token, thread):
        with self._db() as db:
            member, row = self._access(db, token, thread, invitation=True)
            if _blocked(db, member["id"], row["owner"]):
                raise ChatError(404, "That private invitation is unavailable.")
            db.execute("UPDATE private_members SET status='accepted' WHERE thread=? AND participant=?",
                       (thread, member["id"]))

    def private_read(self, token, thread):
        with self._db() as db:
            member, row = self._access(db, token, thread)
            self._expire(db)
            messages = db.execute("""
                SELECT m.*,p.name,d.opened,d.recipient FROM private_messages m
                JOIN participants p ON p.id=m.author
                LEFT JOIN private_deliveries d ON d.message=m.id AND d.recipient=?
                WHERE m.thread=? AND (m.author=? OR d.recipient IS NOT NULL)
                AND NOT EXISTS (SELECT 1 FROM blocks b WHERE (b.viewer=? AND b.target=m.author)
                    OR (b.target=? AND b.viewer=m.author)) ORDER BY m.id DESC LIMIT 100
            """, (member["id"], thread, member["id"], member["id"], member["id"])).fetchall()
            result = []
            for message in reversed(messages):
                own = message["author"] == member["id"]
                state = message["redacted"] or ("opened" if message["opened"] is not None else "available")
                body = message["body"] if message["lifetime"] == "saved" and not message["redacted"] else ""
                result.append({"id": message["id"], "name": message["name"], "author": message["author"],
                               "created": message["created"], "body": body, "own": own,
                               "lifetime": message["lifetime"], "state": state, "expires": message["expires"],
                               "can_open": not own and message["lifetime"] == "view_once" and state == "available"})
                if message["lifetime"] == "saved" and not own:
                    db.execute("UPDATE private_deliveries SET opened=COALESCE(opened,?) WHERE message=? AND recipient=?",
                               (self.clock(), message["id"], member["id"]))
            return {"thread": self._meta(db, row, member["id"]), "messages": result}

    def private_send(self, token, thread, body, lifetime, request_id):
        body = _text(body, MAX_MESSAGE_CHARS, multiline=True)
        request_id = _retry_id(request_id)
        if len(body.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise ChatError(400, "The message exceeds the 2,000-byte text limit.")
        if not isinstance(lifetime, str) or lifetime not in ("saved", "view_once"):
            raise ChatError(400, "Choose Saved or Open once for this message.")
        with self._db() as db:
            member, _ = self._access(db, token, thread)
            self._expire(db)
            previous = db.execute("SELECT id,thread,lifetime,body,redacted FROM private_messages "
                                  "WHERE author=? AND request_id=?", (member["id"], request_id)).fetchone()
            if previous:
                if (previous["thread"] != thread or previous["lifetime"] != lifetime
                        or not previous["redacted"] and previous["body"] != body):
                    raise ChatError(409, "That retry ID belongs to a different message.")
                return {"id": previous["id"], "duplicate": True}
            recipients = [row[0] for row in db.execute("SELECT participant FROM private_members WHERE thread=? "
                                                      "AND participant!=? AND status IN ('accepted','invited')",
                                                      (thread, member["id"]))]
            if not recipients or any(_blocked(db, member["id"], person) for person in recipients):
                raise ChatError(409, "This conversation cannot receive new messages. A member may have left or blocked contact.")
            now = self.clock()
            if now - member["last_sent"] < 2:
                raise ChatError(429, "Please wait two seconds between messages.")
            expires = now + VIEW_ONCE_SECONDS if lifetime == "view_once" else None
            cursor = db.execute("INSERT INTO private_messages(thread,author,body,lifetime,created,expires,request_id) "
                                "VALUES(?,?,?,?,?,?,?)", (thread, member["id"], body, lifetime, now, expires, request_id))
            db.executemany("INSERT INTO private_deliveries VALUES(?,?,NULL)", [(cursor.lastrowid, person) for person in recipients])
            db.execute("UPDATE participants SET last_sent=? WHERE id=?", (now, member["id"]))
            db.execute("DELETE FROM private_messages WHERE thread=? AND id NOT IN "
                       "(SELECT id FROM private_messages WHERE thread=? ORDER BY id DESC LIMIT ?)",
                       (thread, thread, MAX_THREAD_MESSAGES))
            return {"id": cursor.lastrowid, "duplicate": False}

    def private_open_once(self, token, thread, message):
        message = _message_id(message)
        with self._db() as db:
            member, _ = self._access(db, token, thread)
            self._expire(db)
            row = db.execute("SELECT m.*,d.opened FROM private_messages m JOIN private_deliveries d ON d.message=m.id "
                             "WHERE m.id=? AND m.thread=? AND d.recipient=?", (message, thread, member["id"])).fetchone()
            if row is None or row["lifetime"] != "view_once" or _blocked(db, member["id"], row["author"]):
                raise ChatError(404, "That view-once message is unavailable.")
            if row["opened"] is not None or row["redacted"]:
                raise ChatError(410, "This message has already been opened, withdrawn, or expired.")
            result = {"body": row["body"], "display_seconds": 30}
            db.execute("UPDATE private_deliveries SET opened=? WHERE message=? AND recipient=?",
                       (self.clock(), message, member["id"]))
            self._expire(db)
            return result

    def private_delete(self, token, thread, message):
        message = _message_id(message)
        with self._db() as db:
            member, _ = self._access(db, token, thread)
            cursor = db.execute("UPDATE private_messages SET body='',redacted='deleted' WHERE id=? AND thread=? AND author=?",
                                (message, thread, member["id"]))
            if cursor.rowcount != 1:
                raise ChatError(404, "You can withdraw only your own messages in this conversation.")

    def private_leave(self, token, thread):
        with self._db() as db:
            member, _ = self._access(db, token, thread, invitation=True)
            db.execute("UPDATE private_members SET status='left' WHERE thread=? AND participant=?", (thread, member["id"]))
            db.execute("UPDATE private_deliveries SET opened=COALESCE(opened,?) WHERE recipient=? "
                       "AND message IN (SELECT id FROM private_messages WHERE thread=?)", (self.clock(), member["id"], thread))
            self._expire(db)

    def private_export(self, token):
        with self._db() as db:
            member = self._member(db, token)
            self._expire(db)
            rows = db.execute("SELECT t.title,m.body,m.created FROM private_messages m JOIN private_threads t ON t.id=m.thread "
                              "JOIN private_members p ON p.thread=t.id WHERE m.author=? AND p.participant=? "
                              "AND p.status='accepted' AND m.lifetime='saved' AND m.redacted='' ORDER BY m.id DESC LIMIT 1000",
                              (member["id"], member["id"])).fetchall()
            return {"format": "fieldforge-private-sent-messages", "version": 1,
                    "scope": "Latest 1000 saved messages you sent in conversations you still belong to; excludes view-once messages",
                    "messages": [dict(row) for row in reversed(rows)]}

    def private_report(self, token, thread, message, reason):
        message = _message_id(message)
        if not isinstance(reason, str) or reason not in ("spam", "harassment", "unsafe", "other"):
            raise ChatError(400, "Choose a report reason.")
        with self._db() as db:
            member, _ = self._access(db, token, thread)
            if not db.execute("SELECT 1 FROM private_messages m WHERE m.id=? AND m.thread=? AND "
                              "(m.author=? OR EXISTS (SELECT 1 FROM private_deliveries d WHERE d.message=m.id AND d.recipient=?))",
                              (message, thread, member["id"], member["id"])).fetchone():
                raise ChatError(404, "That message is unavailable.")
            db.execute("INSERT INTO private_reports VALUES(?,?,?,?) ON CONFLICT(message,reporter) DO UPDATE SET reason=excluded.reason",
                       (message, member["id"], reason, self.clock()))

    def block(self, token, target, blocked):
        target = _opaque(target)
        if type(blocked) is not bool:
            raise ChatError(400, "Choose a block setting.")
        with self._db() as db:
            member = self._member(db, token)
            if target == member["id"] or not db.execute("SELECT 1 FROM participants WHERE id=?", (target,)).fetchone():
                raise ChatError(400, "Choose another preview member.")
            if blocked:
                db.execute("INSERT OR IGNORE INTO blocks VALUES(?,?)", (member["id"], target))
                for recipient, author in ((member["id"], target), (target, member["id"])):
                    db.execute("UPDATE private_deliveries SET opened=COALESCE(opened,?) WHERE recipient=? AND message IN "
                               "(SELECT id FROM private_messages WHERE author=? AND lifetime='view_once')",
                               (self.clock(), recipient, author))
                self._expire(db)
            else:
                db.execute("DELETE FROM blocks WHERE viewer=? AND target=?", (member["id"], target))

    def reports(self):
        public = super().reports()
        with self._db() as db:
            self._expire(db)
            private = [dict(row) for row in db.execute(
                "SELECT r.message,r.reason,r.created,m.thread,p.name AS reporter,m.lifetime, "
                "CASE WHEN m.lifetime='saved' THEN m.body ELSE '' END AS body "
                "FROM private_reports r JOIN private_messages m ON m.id=r.message "
                "JOIN participants p ON p.id=r.reporter ORDER BY r.created DESC")]
            return [{"scope": "public", **row} for row in public] + [{"scope": "private", **row} for row in private]
