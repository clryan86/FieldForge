"""One resumable board per game, stored locally with optimistic revision checks.

Only these two additive tables are accessed. No household names, notes, library
text, activity history, score uploads, or player profiles are read or written.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from fieldforge.recreation.games import KINDS, Game, decode_game, encode_game

MAX_SAVE_BYTES = 8192


class GameConflict(ValueError):
    """A different window saved this game; reload instead of overwriting it."""


@dataclass(frozen=True)
class SavedGame:
    kind: str
    game: Game | None = None
    revision: int = 0
    updated_at: str = ""
    error: str = ""


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError("duplicate game JSON key")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("non-finite JSON value")


def _kind(kind: str) -> None:
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("choose a supported game")


class GameStore:
    def __init__(self, database: str | Path) -> None:
        self.path = Path(database).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            objects = {row[0]: row[1] for row in db.execute(
                "SELECT name,type FROM sqlite_master WHERE name IN ('recreation_meta','recreation_games')"
            )}
            if objects:
                if objects != {"recreation_meta": "table", "recreation_games": "table"}:
                    raise ValueError("incomplete recreation schema; data was not reset")
                for table, fields in (("recreation_meta", {"key", "value"}),
                                      ("recreation_games", {"kind", "payload", "checksum", "revision", "updated_at"})):
                    columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                    if columns != fields:
                        raise ValueError("unrecognized recreation schema; use a compatible build")
                version = db.execute("SELECT value FROM recreation_meta WHERE key='schema_version'").fetchone()
                if version is None or version[0] != "1":
                    raise ValueError("unsupported recreation schema; use a compatible build")
            else:
                db.execute("CREATE TABLE recreation_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
                db.execute("INSERT INTO recreation_meta VALUES('schema_version','1')")
                db.execute("""CREATE TABLE recreation_games(
                    kind TEXT PRIMARY KEY, payload TEXT NOT NULL, checksum TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision>0), updated_at TEXT NOT NULL
                )""")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=0.25)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def load(self, kind: str) -> SavedGame:
        _kind(kind)
        with self.connect() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT revision,updated_at,length(CAST(payload AS BLOB)) AS size "
                             "FROM recreation_games WHERE kind=?", (kind,)).fetchone()
            if row is None:
                return SavedGame(kind)
            if type(row["revision"]) is not int or row["revision"] <= 0:
                raise ValueError("saved game revision is invalid; data was not reset")
            error = ""
            game = None
            try:
                if type(row["size"]) is not int or row["size"] > MAX_SAVE_BYTES:
                    raise ValueError("saved game is too large")
                payload, checksum = db.execute("SELECT payload,checksum FROM recreation_games WHERE kind=?",
                                               (kind,)).fetchone()
                if not isinstance(payload, str) or hashlib.sha256(payload.encode()).hexdigest() != checksum:
                    raise ValueError("saved game checksum failed")
                game = decode_game(json.loads(payload, object_pairs_hook=_pairs, parse_constant=_constant))
                if game.kind != kind:
                    raise ValueError("saved game does not match its slot")
            except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
                game = None
                error = f"Saved game could not be read: {exc}. It has not been replaced."
            return SavedGame(kind, game, row["revision"], row["updated_at"], error)

    def save(self, game: Game, *, expected_revision: int) -> SavedGame:
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        encoded = json.dumps(encode_game(game), separators=(",", ":"), sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > MAX_SAVE_BYTES:
            raise ValueError("saved game exceeds the size limit")
        checksum = hashlib.sha256(encoded.encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM recreation_games WHERE kind=?", (game.kind,)).fetchone()
            revision = old["revision"] if old else 0
            if revision != expected_revision:
                raise GameConflict("This game changed in another window. Your move was not saved. "
                                   "Choose Reload saved game to see the current board.")
            if old and old["payload"] == encoded and old["checksum"] == checksum:
                return SavedGame(game.kind, game, revision, old["updated_at"])
            db.execute("""INSERT INTO recreation_games VALUES(?,?,?,?,?) ON CONFLICT(kind) DO UPDATE SET
                payload=excluded.payload,checksum=excluded.checksum,revision=excluded.revision,
                updated_at=excluded.updated_at""", (game.kind, encoded, checksum, revision + 1, now))
        return SavedGame(game.kind, game, revision + 1, now)
