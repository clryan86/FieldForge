"""Bounded SQLite storage for the opt-in, loopback-only Commons chat preview.

Preview names are not authenticated accounts. Session secrets are random,
stored only as hashes, and never included in message records or exports.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from fieldforge.online.community import CATEGORIES, CATEGORY_BY_ID

ROOMS = ({"id": "general", "label": "Base camp", "badge": "COMMONS"},) + tuple(
    {"id": item.id, "label": item.label, "badge": item.badge} for item in CATEGORIES
)
ROOM_IDS = {room["id"] for room in ROOMS}
SESSION_SECONDS = 8 * 60 * 60
MAX_MESSAGE_CHARS = 1000
MAX_MESSAGE_BYTES = 2000
MAX_ROOM_MESSAGES = 1000
MAX_PARTICIPANTS = 1000
APPLICATION_ID = 0x46464350  # FFCP: avoid modifying an unrelated SQLite database.


class ChatError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _text(value, maximum, *, multiline=False):
    if not isinstance(value, str):
        raise ChatError(400, "Enter text in this field.")
    for char in value:
        number = ord(char)
        if ((number < 32 and char not in "\t\r\n") or 127 <= number <= 159
                or 0xD800 <= number <= 0xDFFF or number in (0xFFFE, 0xFFFF)
                or 0x202A <= number <= 0x202E or 0x2066 <= number <= 0x2069):
            raise ChatError(400, "Text contains unsupported control characters.")
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not multiline:
        value = " ".join(value.split())
    if not value or len(value) > maximum:
        raise ChatError(400, f"Enter between 1 and {maximum} characters.")
    return value


def _digest(token):
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise ChatError(401, "Join the preview to continue.")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _room(value):
    if not isinstance(value, str) or value not in ROOM_IDS:
        raise ChatError(400, "Choose a supported room.")
    return value


def _message_id(value):
    if type(value) is not int or not 1 <= value < 2**63:
        raise ChatError(400, "Choose a valid message.")
    return value


class ChatStore:
    def __init__(self, path, *, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        with self._db() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            identity = db.execute("PRAGMA application_id").fetchone()[0]
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if ((version == 0 and (identity != 0 or tables))
                    or (version != 0 and identity != APPLICATION_ID)):
                raise ValueError("Choose a separate Commons preview database, not an existing app database.")
            if version not in (0, 1, 2):
                raise ValueError("Unsupported Commons preview database version.")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS participants (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL,
                    skill TEXT NOT NULL, token_hash TEXT UNIQUE, expires REAL NOT NULL,
                    last_sent REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, room TEXT NOT NULL,
                    author TEXT NOT NULL REFERENCES participants(id), body TEXT NOT NULL,
                    created REAL NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
                    request_id TEXT NOT NULL, UNIQUE(author, request_id)
                );
                CREATE INDEX IF NOT EXISTS room_messages ON messages(room, id);
                CREATE TABLE IF NOT EXISTS blocks (
                    viewer TEXT NOT NULL REFERENCES participants(id),
                    target TEXT NOT NULL REFERENCES participants(id),
                    PRIMARY KEY(viewer, target)
                );
                CREATE TABLE IF NOT EXISTS reports (
                    reporter TEXT NOT NULL REFERENCES participants(id),
                    message INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                    reason TEXT NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY(reporter, message)
                );
                PRAGMA application_id=1179009872;
            """)
            db.execute(f"PRAGMA user_version={max(1, version)}")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA secure_delete=ON")
        try:
            # Serialize checks and mutations, including rate limits and revocation.
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _member(self, db, token):
        member = db.execute("SELECT * FROM participants WHERE token_hash=? AND expires>?",
                            (_digest(token), self.clock())).fetchone()
        if member is None:
            raise ChatError(401, "Your preview session ended. Join again to continue.")
        return member

    @staticmethod
    def _public(member):
        skill = CATEGORY_BY_ID.get(member["skill"])
        return {"id": member["id"], "name": member["name"],
                "skill": skill.badge if skill else None,
                "skill_label": skill.label if skill else None,
                "identity": "unverified preview name"}

    def join(self, name, skill, token=None):
        name = _text(name, 40)
        if name.casefold() in {"admin", "administrator", "moderator", "clryan86", "king"}:
            raise ChatError(400, "That name is reserved. Choose another preview name.")
        if not isinstance(skill, str) or skill and skill not in CATEGORY_BY_ID:
            raise ChatError(400, "Choose a supported skill or leave it blank.")
        now = self.clock()
        with self._db() as db:
            if token:
                try:
                    member = self._member(db, token)
                except ChatError:
                    pass
                else:
                    return token, self._public(member)
            db.execute("UPDATE participants SET token_hash=NULL WHERE expires<=?", (now,))
            if db.execute("SELECT COUNT(*) FROM participants").fetchone()[0] >= MAX_PARTICIPANTS:
                raise ChatError(409, "This local preview is full. Use a new preview database.")
            if db.execute("SELECT 1 FROM participants WHERE name_key=? AND expires>? "
                          "AND token_hash IS NOT NULL", (name.casefold(), now)).fetchone():
                raise ChatError(409, "That preview name is in use. Choose another name.")
            token = secrets.token_urlsafe(32)
            participant = secrets.token_hex(12)
            db.execute("INSERT INTO participants(id,name,name_key,skill,token_hash,expires) "
                       "VALUES(?,?,?,?,?,?)", (participant, name, name.casefold(), skill,
                                               _digest(token), now + SESSION_SECONDS))
            return token, self._public(self._member(db, token))

    def read(self, token, room):
        room = _room(room)
        with self._db() as db:
            member = self._member(db, token)
            rows = db.execute("""
                SELECT m.*, p.name, p.skill FROM messages m
                JOIN participants p ON p.id=m.author WHERE m.room=?
                AND NOT EXISTS (SELECT 1 FROM blocks b WHERE b.viewer=? AND b.target=m.author)
                ORDER BY m.id DESC LIMIT 100
            """, (room, member["id"])).fetchall()
            messages = []
            for row in reversed(rows):
                messages.append({"id": row["id"], "author": row["author"], "name": row["name"],
                                 "skill": CATEGORY_BY_ID[row["skill"]].badge if row["skill"] else None,
                                 "body": row["body"], "created": row["created"],
                                 "deleted": bool(row["deleted"]), "own": row["author"] == member["id"]})
            blocked = [dict(row) for row in db.execute(
                "SELECT p.id, p.name FROM participants p JOIN blocks b ON b.target=p.id "
                "WHERE b.viewer=? ORDER BY p.name", (member["id"],))]
            return {"viewer": self._public(member), "room": room, "messages": messages,
                    "blocked": blocked, "rooms": ROOMS}

    def send(self, token, room, body, request_id):
        room = _room(room)
        body = _text(body, MAX_MESSAGE_CHARS, multiline=True)
        if len(body.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise ChatError(400, "The message exceeds the 2,000-byte text limit.")
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9-]{32,36}", request_id):
            raise ChatError(400, "The message needs a valid retry ID.")
        with self._db() as db:
            member = self._member(db, token)
            previous = db.execute("SELECT id,room,body,deleted FROM messages WHERE author=? AND request_id=?",
                                  (member["id"], request_id)).fetchone()
            if previous is not None:
                if previous["room"] != room or previous["body"] != body and not previous["deleted"]:
                    raise ChatError(409, "This retry ID belongs to a different message.")
                return {"id": previous["id"], "duplicate": True}
            now = self.clock()
            if now - member["last_sent"] < 2:
                raise ChatError(429, "Please wait two seconds between messages.")
            cursor = db.execute("INSERT INTO messages(room,author,body,created,request_id) VALUES(?,?,?,?,?)",
                                (room, member["id"], body, now, request_id))
            db.execute("UPDATE participants SET last_sent=? WHERE id=?", (now, member["id"]))
            db.execute("DELETE FROM messages WHERE room=? AND id NOT IN "
                       "(SELECT id FROM messages WHERE room=? ORDER BY id DESC LIMIT ?)",
                       (room, room, MAX_ROOM_MESSAGES))
            return {"id": cursor.lastrowid, "duplicate": False}

    def delete(self, token, message):
        message = _message_id(message)
        with self._db() as db:
            member = self._member(db, token)
            row = db.execute("SELECT author FROM messages WHERE id=?", (message,)).fetchone()
            if row is None or row["author"] != member["id"]:
                raise ChatError(403, "You can delete only your own messages.")
            db.execute("UPDATE messages SET body='',deleted=1 WHERE id=?", (message,))

    def block(self, token, target, blocked):
        if type(blocked) is not bool or not isinstance(target, str):
            raise ChatError(400, "Choose a member and a block setting.")
        with self._db() as db:
            member = self._member(db, token)
            if target == member["id"] or not db.execute(
                    "SELECT 1 FROM participants WHERE id=?", (target,)).fetchone():
                raise ChatError(400, "Choose another preview member.")
            if blocked:
                db.execute("INSERT OR IGNORE INTO blocks VALUES(?,?)", (member["id"], target))
            else:
                db.execute("DELETE FROM blocks WHERE viewer=? AND target=?", (member["id"], target))

    def report(self, token, message, reason):
        message = _message_id(message)
        if not isinstance(reason, str) or reason not in {"spam", "harassment", "unsafe", "other"}:
            raise ChatError(400, "Choose a report reason.")
        with self._db() as db:
            member = self._member(db, token)
            if not db.execute("SELECT 1 FROM messages WHERE id=? AND deleted=0", (message,)).fetchone():
                raise ChatError(404, "That message is no longer available.")
            db.execute("INSERT INTO reports VALUES(?,?,?,?) ON CONFLICT(reporter,message) "
                       "DO UPDATE SET reason=excluded.reason", (member["id"], message, reason, self.clock()))

    def export(self, token):
        with self._db() as db:
            member = self._member(db, token)
            rows = db.execute("SELECT room,body,created FROM messages WHERE author=? AND deleted=0 ORDER BY id DESC LIMIT 1000",
                              (member["id"],)).fetchall()
            return {"format": "fieldforge-commons-preview", "version": 1,
                    "scope": "Latest 1000 retained, undeleted messages from this participant",
                    "participant": self._public(member), "messages": [dict(row) for row in reversed(rows)]}

    def leave(self, token):
        with self._db() as db:
            member = self._member(db, token)
            db.execute("UPDATE participants SET token_hash=NULL,expires=0 WHERE id=?", (member["id"],))

    def reports(self):
        """Local operator review, deliberately unavailable through HTTP."""
        with self._db() as db:
            return [dict(row) for row in db.execute(
                "SELECT r.message,r.reason,r.created,m.room,m.body,m.deleted,p.name AS reporter "
                "FROM reports r JOIN messages m ON m.id=r.message "
                "JOIN participants p ON p.id=r.reporter ORDER BY r.created DESC")]
