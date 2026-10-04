"""Private household editing with conflict-checked writes and minimal change events.

Uses existing household_members/app_events tables; no schema migration or network.
Allowances are user-entered planning assumptions, not personal intake advice.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterator, Mapping

from fieldforge.core.models import HouseholdMember

KINDS = {"Adult": (False, False), "Child": (True, False), "Pet": (False, True)}
FILTERS = ("All profiles", "People", "Children", "Pets")
MAX_ALLOWANCE = 1_000_000_000
NOTICE = (
    "Enter planning allowances from your own appropriate care/preparedness plan. "
    "FieldForge does not prescribe intake or calculate needs from age or species. "
    "Changing a profile changes the household totals used by the resource estimates."
)
PRIVACY = (
    "Names and notes stay in this unencrypted database and personal backups. Use an alias "
    "and only necessary details. Removing a profile is not secure erasure from storage or old backups."
)
_FIELDS = ("name", "daily_water_liters", "daily_calories", "notes", "is_child", "is_pet")


def validate_member(member: HouseholdMember) -> HouseholdMember:
    if not isinstance(member, HouseholdMember):
        raise ValueError("expected a household profile")
    for name, maximum in (("name", 200), ("notes", 10000)):
        value = getattr(member, name)
        if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
            raise ValueError(f"{name} must be text of at most {maximum} characters without NUL")
    if not member.name.strip():
        raise ValueError("name or alias is required")
    water = member.daily_water_liters
    if type(water) not in (int, float) or not 0 < water <= MAX_ALLOWANCE or not math.isfinite(water):
        raise ValueError("liters/day must be a finite positive number, at most 1,000,000,000")
    if type(member.daily_calories) is not int or not 0 <= member.daily_calories <= MAX_ALLOWANCE:
        raise ValueError("kcal/day must be a whole number from 0 to 1,000,000,000")
    if type(member.is_child) is not bool or type(member.is_pet) is not bool:
        raise ValueError("profile flags must be booleans")
    if member.is_child and member.is_pet:
        raise ValueError("choose Child or Pet, not both")
    if member.id is not None and (type(member.id) is not int or member.id <= 0):
        raise ValueError("invalid household profile ID")
    return replace(member, name=member.name.strip(), daily_water_liters=float(water))


def member_from_fields(fields: Mapping[str, str], *, member_id: int | None = None) -> HouseholdMember:
    """No inferred/default allowance, including when selecting Child or Pet."""
    if any(not isinstance(fields.get(key), str) for key in ("name", "kind", "water", "calories", "notes")):
        raise ValueError("complete the name, kind, allowances and notes fields")
    if fields["kind"] not in KINDS:
        raise ValueError("choose Adult, Child, or Pet")
    water_text, calories_text = fields["water"].strip(), fields["calories"].strip()
    if not water_text or not re.fullmatch(r"[0-9]{1,10}", calories_text):
        raise ValueError("enter liters/day and a whole-number kcal/day allowance; blanks are not zero")
    try:
        water = float(water_text)
    except (ValueError, OverflowError) as exc:
        raise ValueError("liters/day must be a finite positive number") from exc
    child, pet = KINDS[fields["kind"]]
    return validate_member(HouseholdMember(fields["name"], water, int(calories_text),
                                           fields["notes"], child, pet, member_id))


def kind_label(member: HouseholdMember) -> str:
    if member.is_child and member.is_pet:
        return "Child + pet: review"
    return "Pet" if member.is_pet else "Child" if member.is_child else "Adult"


def _member(row: sqlite3.Row) -> HouseholdMember:
    # Keep legacy positive-but-nonfinite water values readable so an editor can
    # correct them. Strict validation applies before new saves and total summaries.
    try:
        return HouseholdMember(row["name"], row["daily_water_liters"], row["daily_calories"],
                               row["notes"], bool(row["is_child"]), bool(row["is_pet"]), row["id"])
    except (TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("stored household profile has invalid fields; correct legacy data or restore a compatible backup") from exc


def _token(row: sqlite3.Row) -> str:
    # Local row fingerprint only, never exported as JSON or presented as a security token.
    encoded = json.dumps(dict(row), sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class MemberRecord:
    member: HouseholdMember
    token: str


@dataclass(frozen=True)
class HouseholdSummary:
    people: int
    children: int
    pets: int
    water_liters: float
    calories: int
    zero_calorie_profiles: int


class HouseholdConflict(ValueError):
    """A row changed or disappeared after it was displayed."""


class HouseholdService:
    def __init__(self, database: str | Path) -> None:
        self.path = Path(database).expanduser().resolve()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=0.25)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    def browse(self, query: str = "", kind: str = "All profiles", *, offset: int = 0,
               limit: int = 50) -> tuple[MemberRecord, ...]:
        if not isinstance(query, str) or len(query) > 200 or "\x00" in query:
            raise ValueError("search must be text of at most 200 characters without NUL")
        if not isinstance(kind, str) or kind not in FILTERS:
            raise ValueError("invalid profile filter")
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("invalid household page")
        condition = {"All profiles": "1", "People": "is_pet=0", "Children": "is_child=1 AND is_pet=0",
                     "Pets": "is_pet=1"}[kind]
        with self.connect() as db:
            db.create_function("casefold", 1, lambda value: str(value).casefold())
            rows = db.execute(
                "SELECT * FROM household_members WHERE " + condition +
                " AND instr(casefold(name),?)>0 ORDER BY name COLLATE NOCASE,id LIMIT ? OFFSET ?",
                (query.strip().casefold(), limit, offset),
            ).fetchall()
        return tuple(MemberRecord(_member(row), _token(row)) for row in rows)

    @staticmethod
    def _id(member_id: int) -> None:
        if type(member_id) is not int or member_id <= 0:
            raise ValueError("select a valid household profile")

    def get(self, member_id: int) -> MemberRecord:
        self._id(member_id)
        with self.connect() as db:
            row = db.execute("SELECT * FROM household_members WHERE id=?", (member_id,)).fetchone()
        if row is None:
            raise HouseholdConflict("Profile no longer exists. Refresh the household list.")
        return MemberRecord(_member(row), _token(row))

    @staticmethod
    def _check(db: sqlite3.Connection, member_id: int, expected: str | None) -> sqlite3.Row:
        HouseholdService._id(member_id)
        row = db.execute("SELECT * FROM household_members WHERE id=?", (member_id,)).fetchone()
        if row is None or _token(row) != expected:
            raise HouseholdConflict(
                "This profile changed or was removed in another window. Nothing was overwritten. "
                "Copy any edits you need, cancel, refresh the list and reopen the latest profile."
            )
        return row

    @staticmethod
    def _event(db: sqlite3.Connection, operation: str, member_id: int, changed: list[str]) -> None:
        # Data minimization: no names, note bodies, or allowance values in the event.
        payload = {"operation": operation, "member_id": member_id, "changed_fields": changed}
        db.execute("INSERT INTO app_events(event_type,payload_json) VALUES('household_change',?)",
                   (json.dumps(payload, sort_keys=True, allow_nan=False),))

    def save(self, member: HouseholdMember, *, expected: str | None = None) -> MemberRecord:
        member = validate_member(member)
        values = {key: getattr(member, key) for key in _FIELDS}
        values["is_child"], values["is_pet"] = int(member.is_child), int(member.is_pet)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if member.id is None:
                if expected is not None:
                    raise ValueError("new profiles cannot carry an existing-record token")
                cursor = db.execute(
                    f"INSERT INTO household_members({','.join(_FIELDS)}) VALUES({','.join('?' for _ in _FIELDS)})",
                    tuple(values.values()),
                )
                member_id = int(cursor.lastrowid)
                changed = list(_FIELDS)
            else:
                old = self._check(db, member.id, expected)
                changed = [key for key in _FIELDS if old[key] != values[key]]
                if not changed:
                    return MemberRecord(_member(old), _token(old))
                member_id = member.id
                db.execute(f"UPDATE household_members SET {','.join(key+'=?' for key in _FIELDS)} WHERE id=?",
                           (*values.values(), member_id))
            self._event(db, "add" if member.id is None else "edit", member_id, changed)
            row = db.execute("SELECT * FROM household_members WHERE id=?", (member_id,)).fetchone()
            return MemberRecord(_member(row), _token(row))

    def remove(self, record: MemberRecord) -> None:
        if not isinstance(record, MemberRecord):
            raise ValueError("select an existing profile")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check(db, record.member.id, record.token)
            db.execute("DELETE FROM household_members WHERE id=?", (record.member.id,))
            self._event(db, "remove", record.member.id, [])

    def summary(self) -> HouseholdSummary:
        with self.connect() as db:
            db.execute("BEGIN")
            members = [validate_member(_member(row)) for row in db.execute("SELECT * FROM household_members")]
        return HouseholdSummary(sum(not m.is_pet for m in members), sum(m.is_child for m in members),
                                sum(m.is_pet for m in members), math.fsum(m.daily_water_liters for m in members),
                                sum(m.daily_calories for m in members), sum(m.daily_calories == 0 for m in members))
