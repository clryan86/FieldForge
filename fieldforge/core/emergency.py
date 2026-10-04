"""Saved emergency checklists and private, incident-scoped activity records.

Copies the existing scenario prompts, not new emergency guidance. Completion is
self-reported. No alerts, calls, location detection, or automatic incident creation.
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

from fieldforge.scenarios.engine import available_scenarios, scenario_actions

STATUS_LABELS = {
    "pending": "Pending", "in_progress": "In progress", "blocked": "Blocked",
    "done": "Done (self-reported)",
}
NOTICE = (
    "Planning prompts, not a complete emergency procedure. Official instructions and immediate "
    "life-safety needs take precedence. Marking tasks done or archiving a record does not mean "
    "an emergency is over. This screen does not contact emergency services or receive live alerts."
)
PRIVACY = (
    "Incident titles, checklist notes and logs are private, unencrypted local records. "
    "Full SQLite backups include them; ordinary article packs do not. Use only necessary details."
)
_PRIORITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS emergency_state(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS emergency_sessions(
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
        scenario TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('exercise','incident')),
        template_sha256 TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('active','archived')),
        revision INTEGER NOT NULL CHECK(revision>0), created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS emergency_tasks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES emergency_sessions(id),
        position INTEGER NOT NULL, title TEXT NOT NULL, reason TEXT NOT NULL,
        priority TEXT NOT NULL CHECK(priority IN ('critical','high','medium','low')),
        status TEXT NOT NULL CHECK(status IN ('pending','in_progress','blocked','done')),
        note TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL CHECK(revision>0),
        updated_at TEXT NOT NULL, UNIQUE(session_id,position)
    )""",
    """CREATE TABLE IF NOT EXISTS emergency_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES emergency_sessions(id),
        created_at TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('activity','note')),
        message TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS emergency_sessions_state ON emergency_sessions(state,id)",
    "CREATE INDEX IF NOT EXISTS emergency_log_session ON emergency_log(session_id,id)",
)


def _text(value: str, label: str, maximum: int, *, required: bool = True) -> str:
    if not isinstance(value, str) or len(value) > maximum or any(
        ord(char) < 32 and char not in '\t\r\n' for char in value
    ):
        raise ValueError(f"{label} must be text up to {maximum} characters without control characters")
    if required and not value.strip():
        raise ValueError(f"{label} cannot be empty")
    return value


def _id(value: int) -> None:
    if type(value) is not int or value < 1:
        raise ValueError("select a valid saved record")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def template(name: str) -> tuple[dict[str, str], ...]:
    if not isinstance(name, str) or name not in available_scenarios():
        raise ValueError("choose one of the available scenario templates")
    actions = scenario_actions(name)
    if not 1 <= len(actions) <= 100:
        raise ValueError("template must contain 1 to 100 actions")
    # New sessions sort the existing priority labels; no task text is rephrased.
    rows = tuple({"title": _text(action.title, "task title", 1000),
                  "reason": _text(action.reason, "task reason", 4000),
                  "priority": action.priority.value} for action in actions)
    if any(row["priority"] not in _PRIORITY for row in rows):
        raise ValueError("unsupported task priority")
    return tuple(sorted(rows, key=lambda row: _PRIORITY[row["priority"]]))


@dataclass(frozen=True)
class Incident:
    id: int
    title: str
    scenario: str
    mode: str
    template_sha256: str
    state: str
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Task:
    id: int
    session_id: int
    position: int
    title: str
    reason: str
    priority: str
    status: str
    note: str
    revision: int
    updated_at: str


@dataclass(frozen=True)
class LogEntry:
    id: int
    session_id: int
    created_at: str
    kind: str
    message: str


@dataclass(frozen=True)
class IncidentDetail:
    incident: Incident
    tasks: tuple[Task, ...]
    log: tuple[LogEntry, ...]
    log_count: int

    @property
    def done(self) -> int:
        return sum(task.status == "done" for task in self.tasks)


class EmergencyConflict(ValueError):
    """A stale editor must not overwrite a newer status, note or lifecycle state."""


class EmergencyStore:
    """Additive versioned tables in an existing database, with transactional writes."""

    def __init__(self, database: str | Path) -> None:
        self.path = Path(database).expanduser().resolve()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='emergency_state'").fetchone()
            if exists:
                version = db.execute("SELECT value FROM emergency_state WHERE key='schema_version'").fetchone()
                if version is None or version[0] != "1":
                    raise ValueError("unsupported emergency-record schema; use a compatible FieldForge build")
            elif db.execute("SELECT 1 FROM sqlite_master WHERE name IN "
                            "('emergency_sessions','emergency_tasks','emergency_log')").fetchone():
                raise ValueError("unversioned emergency tables found; no changes made")
            for statement in _SCHEMA:
                db.execute(statement)  # executescript would commit before these schema changes.
            db.execute("INSERT OR IGNORE INTO emergency_state VALUES('schema_version','1')")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        # mode=rw avoids creating a new, mistaken database from a misspelled path.
        db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=0.25)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _session(db: sqlite3.Connection, session_id: int, *, active: bool = False) -> sqlite3.Row:
        _id(session_id)
        row = db.execute("SELECT * FROM emergency_sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise EmergencyConflict("Incident no longer exists; refresh the list.")
        if active and row["state"] != "active":
            raise EmergencyConflict("This incident is archived. Your edits are not saved; reopen it explicitly before editing.")
        return row

    @staticmethod
    def _log(db: sqlite3.Connection, session_id: int, message: str, *, kind: str = "activity") -> None:
        db.execute("INSERT INTO emergency_log(session_id,created_at,kind,message) VALUES(?,?,?,?)",
                   (session_id, _now(), kind, message))

    def create(self, title: str, scenario: str, *, mode: str = "exercise") -> Incident:
        title = _text(title, "incident title", 200).strip()
        if mode not in ("exercise", "incident"):
            raise ValueError("choose exercise or incident mode")
        actions = template(scenario)
        digest = hashlib.sha256(json.dumps(actions, sort_keys=True, ensure_ascii=False,
                                           separators=(",", ":")).encode()).hexdigest()
        now = _now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("""INSERT INTO emergency_sessions
                (title,scenario,mode,template_sha256,state,revision,created_at,updated_at)
                VALUES(?,?,?,?,'active',1,?,?)""", (title, scenario, mode, digest, now, now))
            session_id = int(cursor.lastrowid)
            for index, action in enumerate(actions, 1):
                db.execute("""INSERT INTO emergency_tasks
                    (session_id,position,title,reason,priority,status,note,revision,updated_at)
                    VALUES(?,?,?,?,?,'pending','',1,?)""",
                           (session_id, index, action["title"], action["reason"], action["priority"], now))
            self._log(db, session_id, "Record created; existing scenario prompts copied. Nothing has been marked done.")
            return Incident(**dict(self._session(db, session_id)))

    def browse(self, *, archived: bool = False, offset: int = 0, limit: int = 50) -> tuple[Incident, ...]:
        if type(archived) is not bool or type(offset) is not int or offset < 0:
            raise ValueError("invalid incident filter or page")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("incident page size must be 1 to 100")
        with self.connect() as db:
            rows = db.execute("SELECT * FROM emergency_sessions WHERE (? OR state='active') "
                              "ORDER BY id DESC LIMIT ? OFFSET ?", (archived, limit, offset)).fetchall()
        return tuple(Incident(**dict(row)) for row in rows)

    def detail(self, session_id: int, *, log_limit: int = 100) -> IncidentDetail:
        if type(log_limit) is not int or not 1 <= log_limit <= 200:
            raise ValueError("log limit must be 1 to 200")
        with self.connect() as db:
            db.execute("BEGIN")
            incident = Incident(**dict(self._session(db, session_id)))
            tasks = tuple(Task(**dict(row)) for row in db.execute(
                "SELECT * FROM emergency_tasks WHERE session_id=? ORDER BY position", (session_id,)))
            entries = tuple(LogEntry(**dict(row)) for row in db.execute(
                "SELECT * FROM emergency_log WHERE session_id=? ORDER BY id DESC LIMIT ?", (session_id, log_limit)))
            count = int(db.execute("SELECT COUNT(*) FROM emergency_log WHERE session_id=?", (session_id,)).fetchone()[0])
        return IncidentDetail(incident, tasks, entries, count)

    def update_task(self, task_id: int, *, expected_revision: int, status: str, note: str) -> Task:
        _id(task_id)
        _id(expected_revision)
        if not isinstance(status, str) or status not in STATUS_LABELS:
            raise ValueError("choose a valid checklist status")
        _text(note, "task note", 4000, required=False)
        if status == "blocked" and not note.strip():
            raise ValueError("record why the action is blocked in its note")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM emergency_tasks WHERE id=?", (task_id,)).fetchone()
            if old is None or old["revision"] != expected_revision:
                raise EmergencyConflict("This action changed in another window. Keep your edits, cancel, refresh and reopen it.")
            self._session(db, old["session_id"], active=True)
            if (old["status"], old["note"]) == (status, note):
                return Task(**dict(old))
            now = _now()
            db.execute("UPDATE emergency_tasks SET status=?,note=?,revision=revision+1,updated_at=? WHERE id=?",
                       (status, note, now, task_id))
            db.execute("UPDATE emergency_sessions SET revision=revision+1,updated_at=? WHERE id=?",
                       (now, old["session_id"]))
            # Do not duplicate private note bodies into status-change messages.
            self._log(db, old["session_id"], f"Action {old['position']}: {STATUS_LABELS[old['status']]} → "
                      f"{STATUS_LABELS[status]}." + (" Task note changed." if old["note"] != note else ""))
            return Task(**dict(db.execute("SELECT * FROM emergency_tasks WHERE id=?", (task_id,)).fetchone()))

    def add_note(self, session_id: int, message: str) -> None:
        _text(message, "incident log note", 4000)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._session(db, session_id, active=True)
            self._log(db, session_id, message, kind="note")
            db.execute("UPDATE emergency_sessions SET revision=revision+1,updated_at=? WHERE id=?", (_now(), session_id))

    def set_archived(self, session_id: int, *, expected_revision: int, archived: bool) -> Incident:
        _id(expected_revision)
        if type(archived) is not bool:
            raise ValueError("archived must be a boolean")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = self._session(db, session_id)
            if old["revision"] != expected_revision:
                raise EmergencyConflict("This incident changed since it was displayed. Refresh before archiving or reopening.")
            state = "archived" if archived else "active"
            if old["state"] == state:
                return Incident(**dict(old))
            db.execute("UPDATE emergency_sessions SET state=?,revision=revision+1,updated_at=? WHERE id=?",
                       (state, _now(), session_id))
            self._log(db, session_id, "Record archived. This does not declare the emergency over."
                      if archived else "Record reopened. Previous checklist and notes retained.")
            return Incident(**dict(self._session(db, session_id)))


def render_checklist(detail: IncidentDetail) -> str:
    """Copy-friendly task summary. Excludes task notes and the private activity log."""
    incident = detail.incident
    lines = ["FIELDFORGE — SAVED CHECKLIST", NOTICE, "", f"Title: {incident.title}",
             f"Mode: {incident.mode} | Record: {incident.state} | Template: {incident.scenario}",
             f"Created (device UTC): {incident.created_at}", f"Last changed: {incident.updated_at}",
             f"Template snapshot SHA-256: {incident.template_sha256}",
             f"Self-reported done: {detail.done}/{len(detail.tasks)}. Not a readiness score.", ""]
    for task in detail.tasks:
        lines += [f"{task.position}. [{task.priority.upper()}] {task.title}",
                  f"Status: {STATUS_LABELS[task.status]}", task.reason, ""]
    lines.append("Task notes and incident log excluded. This summary is not a recovery backup.")
    return "\n".join(lines)
