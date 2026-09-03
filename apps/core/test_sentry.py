from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from apps.core.sentry import (
    _CRITICAL_SOURCE,
    _INCIDENT_TAG,
    _SOURCE_TAG,
    _failure_threshold_met,
    before_send,
    capture_critical_message,
)


class SentryAdmissionControlTests(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def _critical_event(self, incident: str) -> dict:
        return {
            "message": incident,
            "tags": {
                _SOURCE_TAG: _CRITICAL_SOURCE,
                _INCIDENT_TAG: incident,
            },
        }

    def _unhandled_event(self, exception_type: str) -> dict:
        return {
            "exception": {
                "values": [
                    {
                        "type": exception_type,
                        "value": "customer@example.com",
                        "stacktrace": {"frames": [{"vars": {"access_token": "secret"}}]},
                    }
                ]
            },
            "request": {"headers": {"Authorization": "Bearer secret"}},
            "user": {"email": "customer@example.com"},
            "breadcrumbs": {"values": [{"message": "sensitive detail"}]},
            "contexts": {"trace": {"trace_id": "trace"}},
            "extra": {"payment_id": "pi_secret"},
            "transaction": "/bids/123/",
        }

    def test_implicit_logging_message_is_not_admitted(self) -> None:
        self.assertIsNone(before_send({"message": "logger error"}, {}))

    def test_unhandled_event_is_redacted_and_deduplicated(self) -> None:
        accepted = before_send(self._unhandled_event("RuntimeError"), {})

        self.assertIsNotNone(accepted)
        self.assertEqual(accepted["exception"]["values"][0]["value"], "redacted")
        self.assertNotIn("request", accepted)
        self.assertNotIn("user", accepted)
        self.assertNotIn("breadcrumbs", accepted)
        self.assertNotIn("contexts", accepted)
        self.assertNotIn("extra", accepted)
        self.assertNotIn("transaction", accepted)
        self.assertNotIn("vars", accepted["exception"]["values"][0]["stacktrace"]["frames"][0])
        self.assertIsNone(before_send(self._unhandled_event("RuntimeError"), {}))

    def test_one_unhandled_event_is_allowed_each_hour(self) -> None:
        self.assertIsNotNone(before_send(self._unhandled_event("RuntimeError"), {}))
        self.assertIsNone(before_send(self._unhandled_event("ValueError"), {}))

    def test_three_critical_events_are_allowed_each_hour(self) -> None:
        allowed = [
            "bid_finalization_retry_exhausted",
            "payment_capture_integrity_mismatch",
            "payment_capture_recording_failure",
        ]
        for incident in allowed:
            self.assertIsNotNone(before_send(self._critical_event(incident), {}))

        self.assertIsNone(
            before_send(self._critical_event("payment_refund_integrity_mismatch"), {})
        )

    def test_unknown_critical_incident_is_not_admitted(self) -> None:
        self.assertIsNone(before_send(self._critical_event("unvetted_incident"), {}))

    def test_failure_threshold_requires_three_occurrences(self) -> None:
        self.assertFalse(
            _failure_threshold_met(
                incident="worker_provider_outage", minimum_occurrences=3, window_seconds=60
            )
        )
        self.assertFalse(
            _failure_threshold_met(
                incident="worker_provider_outage", minimum_occurrences=3, window_seconds=60
            )
        )
        self.assertTrue(
            _failure_threshold_met(
                incident="worker_provider_outage", minimum_occurrences=3, window_seconds=60
            )
        )

    @override_settings(SENTRY_DSN="https://public@example.ingest.sentry.io/1")
    @patch("sentry_sdk.capture_message")
    def test_critical_message_uses_an_explicit_incident(self, capture_message) -> None:
        capture_critical_message("payment_capture_integrity_mismatch")

        capture_message.assert_called_once_with("payment_capture_integrity_mismatch", level="error")
