from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.boards.models import Board
from apps.moderation.models import MessageValidation
from apps.moderation.services.nova_classifier import (
    Classification,
    ClassifierMalformedResponse,
    ClassifierUnavailable,
    _prompt,
    _parse,
)
from apps.moderation.services.rate_limits import RateLimitExceeded, ValidationBusy, candidate_hash
from apps.moderation.services.validation import validate_message
from apps.moderation.services.validators import (
    DeterministicReject,
    validate_display_name_deterministically,
    validate_message_deterministically,
)
from apps.schools.models import Competition, Entity


class DeterministicValidatorTests(TestCase):
    def test_classifier_accepts_only_a_strict_json_object_or_json_code_fence(self) -> None:
        result = _parse('Here is the result:\n```json\n{"decision":"allow","category":"safe","confidence":0.9}\n```')
        self.assertEqual(result, Classification("allow", "safe", 0.9))
        with self.assertRaises(ClassifierMalformedResponse):
            _parse("The candidate is safe.")

    def test_normal_rivalry_trash_talk_and_profanity_are_allowed_locally(self) -> None:
        candidate = validate_message_deterministically("Texas played like crap. Boomer Sooner!")
        self.assertEqual(candidate.original, "Texas played like crap. Boomer Sooner!")

    def test_nova_prompt_protects_public_sports_references_from_personal_info_false_positives(self) -> None:
        prompt = _prompt(content_type="message", policy_version="2026-09-3", candidate="RUDY")
        self.assertIn("standalone first name", prompt)
        self.assertIn("public athlete or coach reference", prompt)
        self.assertIn("not personal information", prompt)
        self.assertIn("contact details or uniquely identifying private-person information", prompt)
        self.assertNotIn("user ID", prompt)
        self.assertNotIn("fan@example.com", prompt)

    def test_messages_with_contact_data_threats_and_urls_are_rejected(self) -> None:
        for candidate in (
            "Visit https://example.com",
            "Text me at 555-123-4567",
            "I will hurt you after the game",
            "Meet me at 123 Main Street",
            "hello\u200bthere",
        ):
            with self.subTest(candidate=candidate), self.assertRaises(DeterministicReject):
                validate_message_deterministically(candidate)

    def test_display_name_format_reserved_names_and_separator_bypasses_are_rejected(self) -> None:
        for candidate in ("ad_min", "Take The Board", "Board--Boss", "-Fan", "Fan-", "Fän"):
            with self.subTest(candidate=candidate), self.assertRaises(DeterministicReject):
                validate_display_name_deterministically(candidate)
        self.assertEqual(validate_display_name_deterministically("Board Boss_7").original, "Board Boss_7")


class ModerationServiceTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.competition = Competition.objects.get(
            name="College Football", slug="college-football", sport="Football"
        )
        self.school = Entity.objects.create(
            competition=self.competition,
            name="Oklahoma", slug="oklahoma", short_name="Oklahoma", group_name="SEC", accent_color="#841617"
        )
        self.represented_entity = Entity.objects.create(
            competition=self.competition,
            name="Texas", slug="texas", short_name="Texas", group_name="SEC", accent_color="#BF5700"
        )
        self.board = Board.objects.create(entity=self.school)
        self.user = UserProfile.objects.create(
            cognito_sub="moderation-test-subject", email="fan@example.com", display_name="TestFan"
        )

    @patch("apps.moderation.services.validation.classify_message")
    def test_cache_hit_reuses_safe_decision_without_another_model_call(self, classify) -> None:
        classify.return_value = Classification("allow", "safe", 0.99)
        first = validate_message(
            user=self.user,
            board=self.board,
            represented_entity=self.represented_entity,
            message="Texas played like crap.",
            remote_addr="127.0.0.1",
        )
        second = validate_message(
            user=self.user,
            board=self.board,
            represented_entity=self.represented_entity,
            message="Texas played like crap.",
            remote_addr="127.0.0.1",
        )
        self.assertEqual(first.decision, MessageValidation.Decision.ALLOW)
        self.assertEqual(second.decision, MessageValidation.Decision.ALLOW)
        classify.assert_called_once()

    @patch(
        "apps.moderation.services.validation.classify_message",
        return_value=Classification("allow", "safe", 0.99),
    )
    def test_rudy_is_a_must_allow_regression_case(self, classify) -> None:
        validation = validate_message(
            user=self.user,
            board=self.board,
            represented_entity=self.represented_entity,
            message="RUDY",
            remote_addr="127.0.0.1",
        )
        self.assertEqual(validation.decision, MessageValidation.Decision.ALLOW)
        self.assertEqual(validation.category, "safe")
        classify.assert_called_once()

    @patch(
        "apps.moderation.services.validation.classify_message",
        return_value=Classification("allow", "safe", 0.99),
    )
    @override_settings(TAKEBOARD_MODERATION_POLICY_VERSION="cache-policy-a")
    def test_policy_version_change_invalidates_decision_cache(self, classify) -> None:
        validate_message(
            user=self.user, board=self.board, represented_entity=self.represented_entity,
            message="Cache version football phrase", remote_addr="127.0.0.1",
        )
        with self.settings(TAKEBOARD_MODERATION_POLICY_VERSION="cache-policy-b"):
            validate_message(
                user=self.user, board=self.board, represented_entity=self.represented_entity,
                message="Cache version football phrase", remote_addr="127.0.0.1",
            )
        self.assertEqual(classify.call_count, 2)

    @patch("apps.moderation.services.validation.classify_message", side_effect=ClassifierUnavailable)
    @override_settings(TAKEBOARD_RATE_LIMITING_ENABLED=True)
    def test_classifier_failure_fails_closed_and_opens_circuit(self, classify) -> None:
        with self.assertRaises(ValidationBusy):
            validate_message(
                user=self.user,
                board=self.board,
                represented_entity=self.represented_entity,
                message="Normal football message.",
                remote_addr="127.0.0.1",
            )
        with self.assertRaises(ValidationBusy):
            validate_message(
                user=self.user,
                board=self.board,
                represented_entity=self.represented_entity,
                message="Another normal message.",
                remote_addr="127.0.0.1",
            )
        classify.assert_called_once()

    @patch("apps.moderation.services.validation.enforce_basic_moderation_limit", side_effect=RateLimitExceeded)
    def test_rate_limit_is_distinct_from_provider_busy(self, enforce_limit) -> None:
        with self.assertRaises(RateLimitExceeded):
            validate_message(
                user=self.user,
                board=self.board,
                represented_entity=self.represented_entity,
                message="Normal football message.",
                remote_addr="127.0.0.1",
            )

        enforce_limit.assert_called_once()
