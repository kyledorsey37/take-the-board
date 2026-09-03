from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from .services.rate_limits import (
    enforce,
    enforce_basic_moderation_limit,
    enforce_checkout_limits,
    record_rejection,
    RateLimitExceeded,
)


@override_settings(TAKEBOARD_RATE_LIMITING_ENABLED=False)
class RateLimitFlagTests(SimpleTestCase):
    def test_disabled_flag_bypasses_moderation_and_checkout_limits(self) -> None:
        for _ in range(20):
            enforce("test", "same-user", limit=1, window_seconds=60)
            enforce_basic_moderation_limit(
                content_type="message", user_id=1, remote_addr="127.0.0.1"
            )
            enforce_checkout_limits(user_id=1, remote_addr="127.0.0.1")


class ModerationRateLimitBehaviorTests(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def tearDown(self) -> None:
        cache.clear()

    def test_defaults_allow_more_message_and_display_name_trials(self) -> None:
        self.assertEqual(settings.TAKEBOARD_RATE_LIMITS["message_request"], (60, 600))
        self.assertEqual(settings.TAKEBOARD_RATE_LIMITS["message_user_uncached"], (20, 600))
        self.assertEqual(settings.TAKEBOARD_RATE_LIMITS["message_ip_uncached"], (60, 600))
        self.assertEqual(settings.TAKEBOARD_RATE_LIMITS["display_name_user_uncached"], (10, 3600))
        self.assertEqual(settings.TAKEBOARD_MODERATION_REJECTION_THRESHOLD, 8)
        self.assertEqual(settings.TAKEBOARD_MODERATION_REJECTION_COOLDOWN_SECONDS, 30)
        self.assertEqual(settings.TAKEBOARD_MODERATION_REJECTION_MAX_SECONDS, 300)

    @override_settings(
        TAKEBOARD_RATE_LIMITING_ENABLED=True,
        TAKEBOARD_MODERATION_REJECTION_THRESHOLD=8,
        TAKEBOARD_MODERATION_REJECTION_COOLDOWN_SECONDS=30,
        TAKEBOARD_MODERATION_REJECTION_MAX_SECONDS=300,
    )
    def test_rejection_backoff_does_not_start_until_the_eighth_rejection(self) -> None:
        for _ in range(7):
            record_rejection(user_id=1, remote_addr="127.0.0.1")

        enforce_basic_moderation_limit(
            content_type="message", user_id=1, remote_addr="127.0.0.1"
        )

        record_rejection(user_id=1, remote_addr="127.0.0.1")
        with self.assertRaises(RateLimitExceeded):
            enforce_basic_moderation_limit(
                content_type="message", user_id=1, remote_addr="127.0.0.1"
            )
