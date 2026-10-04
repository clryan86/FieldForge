"""User-added checklist actions and responsibility labels, without changing templates.

Extends saved Emergency Mode using one additive metadata table. Assignments are
local labels, not notifications, evidence of consent, or qualifications.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from fieldforge.core.emergency import (
    NOTICE,
    STATUS_LABELS,
    EmergencyConflict,
    EmergencyStore,
    Incident,
    IncidentDetail,
    LogEntry,
    Task,
    _id,
    _now,
    _text,
)

PRIORITIES = ("critical", "high", "medium", "low")
MAX_ACTIONS = 200
ORIGIN_LABELS = {"template": "Scenario prompt", "custom": "User-added"}
ASSIGNMENT_NOTICE = (
    "Responsibility is a local name/alias only. No message is sent and no acceptance or "
    "qualification is verified. User-added tasks are your planning text, not reviewed guidance."
)
_SELECT = """SELECT t.*, COALESCE(m.origin,'template') AS origin,
    COALESCE(m.responsible,'') AS responsible
    FROM emergency_tasks t LEFT JOIN emergency_action_metadata m ON m.task_id=t.id"""


def _responsible(value: str) -> str:
    _text(value, "responsibility label", 120, required=False)
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("responsibility label must be one line without control characters")
    return value.strip()


def _details(title: str, reason: str, priority: str) -> tuple[str, str, str]:
    title = _text(title, "custom action title", 200).strip()
    _text(reason, "custom action description", 4000)
    if not isinstance(priority, str) or priority not in PRIORITIES:
        raise ValueError("choose a valid action priority")
    return title, reason, priority


@dataclass(frozen=True)
class AssignedTask(Task):
    origin: str = "template"
    responsible: str = ""


class ActionStore(EmergencyStore):
    """Preserves v1 incident records; metadata has its own additive schema marker."""

    def __init__(self, database: str | Path) -> None:
        super().__init__(database)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute(
                "SELECT value FROM emergency_state WHERE key='action_metadata_schema'"
            ).fetchone()
            table = db.execute(
                "SELECT type FROM sqlite_master WHERE name='emergency_action_metadata'"
            ).fetchone()
            if version is not None:
                if version[0] != "1" or table is None or table[0] != "table":
                    raise ValueError("unsupported action metadata schema; use a compatible FieldForge build")
                columns = {row[1] for row in db.execute("PRAGMA table_info(emergency_action_metadata)")}
                if columns != {"task_id", "origin", "responsible"}:
                    raise ValueError("unrecognized action metadata fields; no changes made")
            elif table is not None:
                raise ValueError("unversioned action metadata found; no changes made")
            else:
                db.execute("""CREATE TABLE emergency_action_metadata(
                    task_id INTEGER PRIMARY KEY REFERENCES emergency_tasks(id) ON DELETE CASCADE,
                    origin TEXT NOT NULL CHECK(origin IN ('template','custom')),
                    responsible TEXT NOT NULL DEFAULT '' CHECK(length(responsible)<=120)
                )""")
                db.execute("INSERT INTO emergency_state VALUES('action_metadata_schema','1')")

    @staticmethod
    def _task(db: sqlite3.Connection, task_id: int) -> AssignedTask:
        _id(task_id)
        row = db.execute(_SELECT + " WHERE t.id=?", (task_id,)).fetchone()
        if row is None:
            raise EmergencyConflict("Action no longer exists; refresh the checklist.")
        return AssignedTask(**dict(row))

    def get_task(self, task_id: int) -> AssignedTask:
        with self.connect() as db:
            return self._task(db, task_id)

    def detail(self, session_id: int, *, log_limit: int = 100) -> IncidentDetail:
        if type(log_limit) is not int or not 1 <= log_limit <= 200:
            raise ValueError("log limit must be 1 to 200")
        with self.connect() as db:
            db.execute("BEGIN")
            incident = Incident(**dict(self._session(db, session_id)))
            tasks = tuple(AssignedTask(**dict(row)) for row in db.execute(
                _SELECT + " WHERE t.session_id=? ORDER BY t.position", (session_id,)))
            entries = tuple(LogEntry(**dict(row)) for row in db.execute(
                "SELECT * FROM emergency_log WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, log_limit)))
            count = db.execute("SELECT COUNT(*) FROM emergency_log WHERE session_id=?", (session_id,)).fetchone()[0]
        return IncidentDetail(incident, tasks, entries, count)

    def add_custom(self, session_id: int, *, expected_revision: int, title: str, reason: str,
                   priority: str = "medium", responsible: str = "") -> AssignedTask:
        """Append a pending user action. A stale or archived incident is not changed."""
        _id(expected_revision)
        title, reason, priority = _details(title, reason, priority)
        responsible = _responsible(responsible)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            incident = self._session(db, session_id, active=True)
            if incident["revision"] != expected_revision:
                raise EmergencyConflict("This incident changed while you were adding an action. "
                                        "Keep your text, cancel, refresh and try again.")
            count, position = db.execute("SELECT COUNT(*),COALESCE(MAX(position),0)+1 "
                                         "FROM emergency_tasks WHERE session_id=?", (session_id,)).fetchone()
            if count >= MAX_ACTIONS:
                raise ValueError(f"this checklist has reached the {MAX_ACTIONS}-action limit")
            now = _now()
            cursor = db.execute("""INSERT INTO emergency_tasks
                (session_id,position,title,reason,priority,status,note,revision,updated_at)
                VALUES(?,?,?,?,?,'pending','',1,?)""", (session_id, position, title, reason, priority, now))
            task_id = int(cursor.lastrowid)
            db.execute("INSERT INTO emergency_action_metadata VALUES(?,'custom',?)", (task_id, responsible))
            db.execute("UPDATE emergency_sessions SET revision=revision+1,updated_at=? WHERE id=?", (now, session_id))
            self._log(db, session_id, f"User-added action {position} created as Pending. "
                      "No notification sent; task details and responsibility label are stored only with the action.")
            return self._task(db, task_id)

    def update_task(self, task_id: int, *, expected_revision: int, status: str, note: str,
                    responsible: str | None = None, title: str | None = None,
                    reason: str | None = None, priority: str | None = None) -> AssignedTask:
        """Change progress/responsibility together; template wording stays frozen."""
        _id(expected_revision)
        if not isinstance(status, str) or status not in STATUS_LABELS:
            raise ValueError("choose a valid checklist status")
        _text(note, "task note", 4000, required=False)
        if status == "blocked" and not note.strip():
            raise ValueError("record why the action is blocked in its note")
        if responsible is not None:
            responsible = _responsible(responsible)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = self._task(db, task_id)
            if old.revision != expected_revision:
                raise EmergencyConflict("This action changed in another window. "
                                        "Keep your edits, cancel, refresh and reopen it.")
            self._session(db, old.session_id, active=True)
            new_details = (old.title if title is None else title, old.reason if reason is None else reason,
                           old.priority if priority is None else priority)
            if old.origin == "template" and new_details != (old.title, old.reason, old.priority):
                raise ValueError("scenario prompt wording and priority are frozen; add a user task instead")
            if old.origin == "custom":
                new_details = _details(*new_details)
                if new_details != (old.title, old.reason, old.priority) and status == "done":
                    raise ValueError("Task details changed. Choose Pending, In progress or Blocked, "
                                     "save and review the changed action before marking it done.")
            owner = old.responsible if responsible is None else responsible
            if (*new_details, status, note, owner) == (old.title, old.reason, old.priority, old.status, old.note, old.responsible):
                return old
            now = _now()
            db.execute("""UPDATE emergency_tasks SET title=?,reason=?,priority=?,status=?,note=?,
                revision=revision+1,updated_at=? WHERE id=?""", (*new_details, status, note, now, task_id))
            db.execute("INSERT INTO emergency_action_metadata VALUES(?,?,?) ON CONFLICT(task_id) "
                       "DO UPDATE SET responsible=excluded.responsible", (task_id, old.origin, owner))
            db.execute("UPDATE emergency_sessions SET revision=revision+1,updated_at=? WHERE id=?", (now, old.session_id))
            changes = []
            if status != old.status:
                changes.append(f"{STATUS_LABELS[old.status]} → {STATUS_LABELS[status]}")
            if note != old.note:
                changes.append("private note changed")
            if owner != old.responsible:
                changes.append("responsibility label changed (no message sent)")
            if new_details != (old.title, old.reason, old.priority):
                changes.append("user-added task details changed")
            self._log(db, old.session_id, f"Action {old.position}: " + "; ".join(changes) + ".")
            return self._task(db, task_id)


def render_action_checklist(detail: IncidentDetail) -> str:
    """Explicit copy excludes assignment labels, notes and logs, not user task text."""
    incident = detail.incident
    lines = ["FIELDFORGE — SAVED CHECKLIST", NOTICE, ASSIGNMENT_NOTICE, "",
             f"Title: {incident.title}", f"Mode: {incident.mode} | Record: {incident.state}",
             f"Original scenario: {incident.scenario} | Device UTC update: {incident.updated_at}",
             f"Original template SHA-256: {incident.template_sha256}",
             "The original template checksum does not cover user-added tasks or later progress.",
             f"Done (self-reported): {detail.done}/{len(detail.tasks)}. Not a readiness score.", ""]
    for task in detail.tasks:
        origin = ORIGIN_LABELS[getattr(task, "origin", "template")]
        lines.extend((f"{task.position}. [{task.priority.upper()}] [{origin}] {task.title}",
                      f"Status: {STATUS_LABELS[task.status]}", task.reason, ""))
    lines.append("Responsibility labels, private task notes and incident log excluded. "
                 "Titles/descriptions may still contain personal text. This is not a recovery backup.")
    return "\n".join(lines)
