from django.test import SimpleTestCase, override_settings

from .services.rate_limits import (
    enforce,
    enforce_basic_moderation_limit,
    enforce_checkout_limits,
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
