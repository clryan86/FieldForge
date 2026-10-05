"""Unit tests for the public-safe FieldForge Commons profile contract."""

import unittest

from fieldforge.online.community import (
    COMMUNITY_NAME,
    CommunityValidationError,
    assess_skills,
    badge_for,
    validate_profile,
)


def profile(*, visibility="commons", assessment=None):
    return {
        "display_name": "Field Helper",
        "bio": "Water and food planning",
        "visibility": visibility,
        "assessment": assessment or {
            "interests": ["water", "food", "medical"],
            "experience": {"water": "practiced", "food": "learning"},
            "contributions": ["hands_on", "teach"],
        },
        "photo_asset_id": None,
    }


class CommunityProfileTests(unittest.TestCase):
    def test_community_brand_is_neutral_and_stable(self):
        self.assertEqual(COMMUNITY_NAME, "FieldForge Commons")

    def test_assessment_orders_self_reported_categories_by_experience(self):
        assessment = assess_skills(profile()["assessment"])
        self.assertEqual(assessment["recommended_categories"], ["water", "food", "medical"])
        self.assertEqual(assessment["experience"]["medical"], "exploring")
        self.assertEqual(assessment["status"], "self_reported")
        self.assertFalse(assessment["credential_verified"])

    def test_public_profile_marks_badges_self_reported(self):
        result = validate_profile(profile())
        self.assertEqual(result["categories"], ["water", "food", "medical"])
        self.assertEqual(result["skill_status"], "self-reported")
        self.assertFalse(result["credential_verified"])

    def test_private_visibility_hides_skills_and_contribution_preferences(self):
        result = validate_profile(profile(visibility="private"))
        self.assertEqual(result["categories"], [])
        self.assertEqual(result["contributions"], [])
        self.assertIsNone(result["skill_status"])

    def test_badge_uses_text_code_instead_of_red_cross_emblem(self):
        badge = badge_for("medical")
        self.assertEqual(badge["badge"], "MED")
        self.assertEqual(badge["status"], "self-reported")

    def test_assessment_rejects_unknown_category_duplicate_or_too_many(self):
        for interests in (["unknown"], ["medical", "medical"],
                          ["medical", "food", "construction", "water", "power", "machinery"]):
            with self.subTest(interests=interests):
                value = profile()["assessment"].copy()
                value["interests"] = interests
                with self.assertRaises(CommunityValidationError):
                    assess_skills(value)

    def test_experience_must_belong_to_selected_interests(self):
        value = profile()["assessment"].copy()
        value["experience"] = {"medical": "professionally_qualified", "not_selected": "practiced"}
        with self.assertRaises(CommunityValidationError):
            assess_skills(value)

    def test_profile_rejects_unexpected_admin_or_credential_fields(self):
        for key in ("role", "is_admin", "verified_credentials"):
            value = profile()
            value[key] = True
            with self.subTest(key=key), self.assertRaises(CommunityValidationError):
                validate_profile(value)

    def test_profile_rejects_markup_like_controls_and_unissued_photo_urls(self):
        value = profile()
        value["bio"] = "hello\u202eexample"
        with self.assertRaises(CommunityValidationError):
            validate_profile(value)
        value = profile()
        value["photo_asset_id"] = "https://example.com/avatar.svg"
        with self.assertRaises(CommunityValidationError):
            validate_profile(value)


if __name__ == "__main__":
    unittest.main()
