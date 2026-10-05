"""Shared, privacy-conscious profile and skill assessment for FieldForge Commons.

This module defines the profile contract used by future community clients. It
does not authenticate users, verify credentials, store profile photos, or claim
that a self-reported skill is a qualification.
"""

from __future__ import annotations

from dataclasses import dataclass

COMMUNITY_NAME = "FieldForge Commons"
MAX_INTERESTS = 5
MAX_DISPLAY_NAME = 60
MAX_BIO = 500
MAX_HELP_AREAS = 5


@dataclass(frozen=True)
class SkillCategory:
    id: str
    label: str
    badge: str


CATEGORIES = (
    SkillCategory("medical", "Medical & first aid", "MED"),
    SkillCategory("food", "Food, farming & wild foods", "FOOD"),
    SkillCategory("construction", "Construction & repair", "BUILD"),
    SkillCategory("water", "Water & sanitation", "WATER"),
    SkillCategory("power", "Power & utilities", "POWER"),
    SkillCategory("machinery", "Vehicles & machinery", "MECH"),
    SkillCategory("logistics", "Logistics & supplies", "LOG"),
    SkillCategory("communications", "Communications & technology", "COMMS"),
    SkillCategory("education", "Education & training", "TEACH"),
    SkillCategory("navigation", "Maps & navigation", "MAP"),
    SkillCategory("safety", "Community safety & preparedness", "SAFE"),
    SkillCategory("research", "Research & documentation", "RESEARCH"),
)
CATEGORY_BY_ID = {item.id: item for item in CATEGORIES}
EXPERIENCE_LEVELS = ("exploring", "learning", "practiced", "professionally_qualified")
CONTRIBUTION_TYPES = ("hands_on", "teach", "coordinate", "research", "remote")
VISIBILITIES = ("private", "commons")


class CommunityValidationError(ValueError):
    """A profile or assessment is outside its bounded public schema."""


def _text(value, name, maximum, *, optional=False):
    if not isinstance(value, str):
        raise CommunityValidationError(f"{name} must be text.")
    for char in value:
        code = ord(char)
        if ((code < 32 and char not in "\t\n\r") or 127 <= code <= 159
                or 0xD800 <= code <= 0xDFFF or code in (0xFFFE, 0xFFFF)
                or 0x202A <= code <= 0x202E or 0x2066 <= code <= 0x2069):
            raise CommunityValidationError(f"{name} contains unsupported control characters.")
    clean = " ".join(value.split())
    if (not optional and not clean) or len(clean) > maximum:
        raise CommunityValidationError(f"{name} must contain at most {maximum} characters.")
    return clean


def _choices(value, allowed, name, maximum):
    if not isinstance(value, list) or len(value) > maximum:
        raise CommunityValidationError(f"Choose no more than {maximum} {name}.")
    if any(not isinstance(item, str) or item not in allowed for item in value):
        raise CommunityValidationError(f"{name.capitalize()} contains an unknown choice.")
    if len(set(value)) != len(value):
        raise CommunityValidationError(f"{name.capitalize()} cannot contain duplicates.")
    return tuple(value)


def assess_skills(value):
    """Validate onboarding answers and return ordered, self-reported categories.

    Answers are recommendations the member can edit. This function does not
    infer credentials, suitability for a job, or permission to practice.
    """
    if not isinstance(value, dict) or set(value) != {"interests", "experience", "contributions"}:
        raise CommunityValidationError("Assessment needs interests, experience, and contributions.")
    interests = _choices(value["interests"], CATEGORY_BY_ID, "interests", MAX_INTERESTS)
    experience = value["experience"]
    if not isinstance(experience, dict) or experience.keys() - set(interests):
        raise CommunityValidationError("Experience levels must match selected interests.")
    if any(level not in EXPERIENCE_LEVELS for level in experience.values()):
        raise CommunityValidationError("Choose a supported experience level for each interest.")
    contributions = _choices(value["contributions"], CONTRIBUTION_TYPES,
                              "contribution types", MAX_HELP_AREAS)
    priority = {level: index for index, level in enumerate(EXPERIENCE_LEVELS)}
    ordered = sorted(interests, key=lambda category: (
        -priority.get(experience.get(category, "exploring"), 0), interests.index(category)))
    return {
        "recommended_categories": list(ordered),
        "experience": {category: experience.get(category, "exploring") for category in interests},
        "contributions": list(contributions),
        "status": "self_reported",
        "credential_verified": False,
    }


def validate_profile(value):
    """Return a public-safe profile record with explicit directory consent."""
    required = {"display_name", "bio", "visibility", "assessment", "photo_asset_id"}
    if not isinstance(value, dict) or value.keys() != required:
        raise CommunityValidationError("Profile fields do not match the supported schema.")
    display_name = _text(value["display_name"], "Display name", MAX_DISPLAY_NAME)
    bio = _text(value["bio"], "Bio", MAX_BIO, optional=True)
    visibility = value["visibility"]
    if visibility not in VISIBILITIES:
        raise CommunityValidationError("Choose private or Commons directory visibility.")
    assessment = assess_skills(value["assessment"])
    photo_id = value["photo_asset_id"]
    if photo_id is not None and (not isinstance(photo_id, str) or
                                 not 1 <= len(photo_id) <= 80 or
                                 any(not (c.isascii() and (c.isalnum() or c in "-_"))
                                     for c in photo_id)):
        raise CommunityValidationError("Profile pictures must use a server-issued asset ID.")
    public = visibility == "commons"
    return {
        "display_name": display_name,
        "bio": bio,
        "visibility": visibility,
        "photo_asset_id": photo_id,
        "categories": assessment["recommended_categories"] if public else [],
        "skill_status": "self-reported" if public and assessment["recommended_categories"] else None,
        "contributions": assessment["contributions"] if public else [],
        "credential_verified": False,
    }


def badge_for(category_id):
    """Create a text badge that explicitly identifies member-reported skills."""
    category = CATEGORY_BY_ID.get(category_id)
    if category is None:
        raise CommunityValidationError("Unknown skill category.")
    return {
        "category": category.id,
        "label": category.label,
        "badge": category.badge,
        "status": "self-reported",
    }
