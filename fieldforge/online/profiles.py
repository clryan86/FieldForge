"""Optional local Commons profiles with explicit publication and photo consent.

Private questionnaire answers and photo originals are never directory records.
Photos are normalized before storage and served only by authenticated POSTs.
An opaque directory ID is separate from a participant's private contact code.
"""

from __future__ import annotations

import base64
import json
import re
import secrets
import threading

from fieldforge.online.accounts import RESERVED
from fieldforge.online.chat_store import ChatError
from fieldforge.online.community import (
    CATEGORIES,
    CATEGORY_BY_ID,
    CommunityValidationError,
    assess_skills,
    badge_for,
    validate_profile,
)
from fieldforge.online.owner import OWNER_USERNAME, OwnerStore

DIRECTORY_PAGE_SIZE = 12
PROFILE_FIELDS = {"display_name", "bio", "visibility", "share_skills", "share_photo", "assessment"}
EXPERIENCE_LABELS = (
    ("exploring", "Exploring"), ("learning", "Learning"), ("practiced", "Practiced"),
    ("professionally_qualified", "Professional experience (self-reported)"),
)
CONTRIBUTION_LABELS = (
    ("hands_on", "Hands-on help"), ("teach", "Teaching"), ("coordinate", "Coordinating"),
    ("research", "Research"), ("remote", "Remote help"),
)


def _revision(value):
    if type(value) is not int or not 0 <= value < 2**53 - 1:
        raise ChatError(400, "Choose a valid saved profile revision.")
    return value


def _asset_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ChatError(404, "That profile or photo is unavailable.")
    return value


def _photo_support():
    try:
        from PIL import ImageFile
    except ImportError:
        return False
    return not ImageFile.LOAD_TRUNCATED_IMAGES


def _default_profile(member):
    return {"display_name": member["name"], "bio": "", "visibility": "private",
            "share_skills": False, "share_photo": False,
            "assessment": {"interests": [], "experience": {}, "contributions": []},
            "photo_asset_id": None}


class ProfileStore(OwnerStore):
    def __init__(self, path, **kwargs):
        super().__init__(path, **kwargs)
        self._photo_slots = threading.BoundedSemaphore(2)
        with self._db() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            db.executescript("""
                CREATE TABLE IF NOT EXISTS profiles (
                    participant TEXT PRIMARY KEY REFERENCES accounts(participant) ON DELETE CASCADE,
                    profile_id TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL, bio TEXT NOT NULL,
                    visibility TEXT NOT NULL CHECK(visibility IN ('private','commons')),
                    share_skills INTEGER NOT NULL CHECK(share_skills IN (0,1)),
                    share_photo INTEGER NOT NULL CHECK(share_photo IN (0,1)),
                    assessment TEXT NOT NULL, photo_asset_id TEXT UNIQUE, photo_png BLOB,
                    revision INTEGER NOT NULL, saved INTEGER NOT NULL CHECK(saved IN (0,1)),
                    updated REAL NOT NULL,
                    CHECK((photo_asset_id IS NULL) = (photo_png IS NULL))
                );
            """)
            db.execute(f"PRAGMA user_version={max(5, version)}")

    def _profile_member(self, db, token):
        member = self._member(db, token)
        if not member["account_name"]:
            raise ChatError(403, "Save your guest as a local account before creating a profile.")
        return member

    @staticmethod
    def _row(db, member):
        return db.execute("SELECT * FROM profiles WHERE participant=?", (member["id"],)).fetchone()

    @staticmethod
    def _check_revision(row, revision):
        expected = row["revision"] if row is not None else 0
        if _revision(revision) != expected:
            raise ChatError(409, "Your saved profile changed. Reload the saved profile before trying again; your draft was not saved.")

    @staticmethod
    def _profile(member, row):
        if row is None or not row["saved"]:
            return _default_profile(member)
        return {"display_name": row["display_name"], "bio": row["bio"],
                "visibility": row["visibility"], "share_skills": bool(row["share_skills"]),
                "share_photo": bool(row["share_photo"]), "assessment": json.loads(row["assessment"]),
                "photo_asset_id": row["photo_asset_id"]}

    def _result(self, member, row):
        return {"viewer": self._public(member), "profile": self._profile(member, row),
                "revision": row["revision"] if row is not None else 0,
                "saved": bool(row is not None and row["saved"]), "photo_uploads": _photo_support(),
                "categories": [{"id": c.id, "label": c.label, "badge": c.badge} for c in CATEGORIES],
                "experience_levels": [{"id": key, "label": label} for key, label in EXPERIENCE_LABELS],
                "contribution_types": [{"id": key, "label": label} for key, label in CONTRIBUTION_LABELS]}

    def _write(self, db, member, row, profile, *, photo=None, saved=True):
        revision = (row["revision"] if row is not None else 0) + 1
        profile_id = row["profile_id"] if row is not None and row["saved"] and saved else secrets.token_hex(16)
        # photo=None preserves the current normalized photo. A (None, None) pair removes it.
        photo_id, photo_png = photo if photo is not None else (
            (row["photo_asset_id"], row["photo_png"]) if row is not None else (None, None))
        db.execute("""
            INSERT INTO profiles VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(participant) DO UPDATE SET
                profile_id=excluded.profile_id, display_name=excluded.display_name,
                bio=excluded.bio, visibility=excluded.visibility, share_skills=excluded.share_skills,
                share_photo=excluded.share_photo, assessment=excluded.assessment,
                photo_asset_id=excluded.photo_asset_id, photo_png=excluded.photo_png,
                revision=excluded.revision, saved=excluded.saved, updated=excluded.updated
        """, (member["id"], profile_id, profile["display_name"], profile["bio"],
              profile["visibility"], profile["share_skills"], profile["share_photo"],
              json.dumps(profile["assessment"], ensure_ascii=False, separators=(",", ":")),
              photo_id, photo_png, revision, saved, self.clock()))
        return self._result(member, self._row(db, member))

    def profile_get(self, token):
        with self._db() as db:
            member = self._profile_member(db, token)
            return self._result(member, self._row(db, member))

    def profile_save(self, token, profile, revision):
        if not isinstance(profile, dict) or set(profile) != PROFILE_FIELDS:
            raise ChatError(400, "Unsupported profile fields. Photos are assigned only by the upload service.")
        if type(profile["share_skills"]) is not bool or type(profile["share_photo"]) is not bool:
            raise ChatError(400, "Choose whether to share skills and your photo.")
        with self._db() as db:
            member = self._profile_member(db, token)
            row = self._row(db, member)
            self._check_revision(row, revision)
            photo_id = row["photo_asset_id"] if row is not None else None
            values = {key: profile[key] for key in ("display_name", "bio", "visibility", "assessment")}
            try:
                clean = validate_profile({**values, "photo_asset_id": photo_id})
                assessment = assess_skills(profile["assessment"])
            except CommunityValidationError as exc:
                raise ChatError(400, str(exc)) from None
            name_key = clean["display_name"].casefold()
            if name_key == "closed account" or name_key in RESERVED and member["account_name"] != OWNER_USERNAME:
                raise ChatError(400, "That display name is reserved. Choose another name.")
            if profile["share_photo"] and photo_id is None:
                raise ChatError(400, "Upload a photo before choosing to share it.")
            stored = {**profile, "display_name": clean["display_name"], "bio": clean["bio"],
                      "assessment": {"interests": list(profile["assessment"]["interests"]),
                                     "experience": assessment["experience"],
                                     "contributions": assessment["contributions"]}}
            return self._write(db, member, row, stored)

    def profile_photo_upload(self, token, encoded, revision):
        # Authenticate and check the edit before spending any work on a raster decoder.
        with self._db() as db:
            member = self._profile_member(db, token)
            self._check_revision(self._row(db, member), revision)
        if not self._photo_slots.acquire(blocking=False):
            raise ChatError(429, "The photo service is busy. Try again in a moment.")
        try:
            from fieldforge.online.profile_photos import (
                PhotoSupportUnavailable,
                ProfilePhotoError,
                normalize_profile_photo,
            )

            try:
                png = normalize_profile_photo(encoded)
            except PhotoSupportUnavailable:
                raise ChatError(503, 'Photo uploads need the optional package: pip install ".[commons]"') from None
            except ProfilePhotoError as exc:
                raise ChatError(400, str(exc)) from None
            with self._db() as db:
                # A concurrent sign-out, suspension or profile edit also cancels this upload.
                member = self._profile_member(db, token)
                row = self._row(db, member)
                self._check_revision(row, revision)
                profile = self._profile(member, row)
                profile["share_photo"] = False
                return self._write(db, member, row, profile, photo=(secrets.token_hex(16), png))
        finally:
            self._photo_slots.release()

    def profile_photo_remove(self, token, revision):
        with self._db() as db:
            member = self._profile_member(db, token)
            row = self._row(db, member)
            self._check_revision(row, revision)
            profile = self._profile(member, row)
            profile["share_photo"] = False
            return self._write(db, member, row, profile, photo=(None, None))

    @staticmethod
    def _blocked(db, viewer, target):
        return db.execute("SELECT 1 FROM blocks WHERE (viewer=? AND target=?) OR (viewer=? AND target=?)",
                          (viewer, target, target, viewer)).fetchone()

    def _visible(self, db, member, row):
        return (row is not None and row["saved"] and row["visibility"] == "commons"
                and not self._suspended(db, row["participant"])
                and not self._blocked(db, member["id"], row["participant"]))

    def profile_photo_read(self, token, asset_id):
        asset_id = _asset_id(asset_id)
        with self._db() as db:
            member = self._member(db, token)
            row = db.execute("SELECT * FROM profiles WHERE photo_asset_id=?", (asset_id,)).fetchone()
            own = row is not None and row["participant"] == member["id"]
            if row is None or not own and not (row["share_photo"] and self._visible(db, member, row)):
                raise ChatError(404, "That profile or photo is unavailable.")
            return {"asset_id": asset_id, "mime_type": "image/png",
                    "encoded": base64.b64encode(row["photo_png"]).decode("ascii")}

    def profile_directory(self, token, query, category, offset):
        if (not isinstance(query, str) or len(query) > 60
                or any(ord(char) < 32 or 127 <= ord(char) <= 159 or 0xD800 <= ord(char) <= 0xDFFF for char in query)):
            raise ChatError(400, "Search profiles with up to 60 characters of plain text.")
        if not isinstance(category, str) or category and category not in CATEGORY_BY_ID:
            raise ChatError(400, "Choose a supported skill category.")
        if type(offset) is not int or not 0 <= offset <= 1000 or offset % DIRECTORY_PAGE_SIZE:
            raise ChatError(400, "Choose a valid directory page.")
        query = " ".join(query.split()).casefold()
        with self._db() as db:
            member = self._member(db, token)
            # The participant limit bounds this scan to 1,000 small records. Photo bytes are
            # deliberately excluded, and unpublished profiles never leave this query.
            rows = db.execute("""
                SELECT p.participant,p.profile_id,p.display_name,p.bio,p.share_skills,
                       p.share_photo,p.assessment,p.photo_asset_id,a.username
                FROM profiles p JOIN accounts a ON a.participant=p.participant
                WHERE p.saved=1 AND p.visibility='commons'
                AND NOT EXISTS (SELECT 1 FROM participant_controls c
                                WHERE c.participant=p.participant AND c.suspended=1)
                AND NOT EXISTS (SELECT 1 FROM blocks b WHERE
                    (b.viewer=? AND b.target=p.participant) OR (b.viewer=p.participant AND b.target=?))
            """, (member["id"], member["id"])).fetchall()
            matches = []
            for row in rows:
                if query and query not in " ".join((row["display_name"], row["username"], row["bio"])).casefold():
                    continue
                answers = json.loads(row["assessment"])
                assessment = assess_skills(answers)
                # Experience answers remain private, including their relative ranking.
                # Publish the member's selected order, never an experience-derived order.
                interests = answers["interests"] if row["share_skills"] else []
                if category and category not in interests:
                    continue
                matches.append({"profile_id": row["profile_id"], "display_name": row["display_name"],
                                "username": row["username"], "bio": row["bio"],
                                "categories": [badge_for(value) for value in interests],
                                "contributions": assessment["contributions"] if row["share_skills"] else [],
                                "photo_asset_id": row["photo_asset_id"] if row["share_photo"] else None,
                                "credential_verified": False})
            matches.sort(key=lambda item: (item["display_name"].casefold(), item["username"]))
            return {"profiles": matches[offset:offset + DIRECTORY_PAGE_SIZE], "total": len(matches),
                    "offset": offset, "limit": DIRECTORY_PAGE_SIZE}

    def profile_block(self, token, profile_id):
        profile_id = _asset_id(profile_id)
        with self._db() as db:
            member = self._member(db, token)
            row = db.execute("SELECT * FROM profiles WHERE profile_id=?", (profile_id,)).fetchone()
            if not self._visible(db, member, row):
                raise ChatError(404, "That profile or photo is unavailable.")
            target = row["participant"]
        # Reuse private-chat blocking so pending open-once deliveries are also consumed.
        self.block(token, target, True)
        return {"ok": True}

    def profile_delete(self, token, revision):
        with self._db() as db:
            member = self._profile_member(db, token)
            row = self._row(db, member)
            self._check_revision(row, revision)
            profile = _default_profile(member)
            profile["display_name"] = ""
            # Retain only an empty revision marker so stale tabs cannot resurrect deleted data.
            return self._write(db, member, row, profile, photo=(None, None), saved=False)

    def profile_export(self, token):
        with self._db() as db:
            member = self._profile_member(db, token)
            row = self._row(db, member)
            photo = None
            if row is not None and row["saved"] and row["photo_png"] is not None:
                photo = {"mime_type": "image/png", "encoded": base64.b64encode(row["photo_png"]).decode("ascii")}
            return {"format": "fieldforge-commons-profile", "version": 1,
                    "profile": self._profile(member, row), "photo": photo, "exported_at": self.clock()}
