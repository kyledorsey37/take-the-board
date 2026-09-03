from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.bidding.models import Bid
from apps.boards.models import Board, BoardTakeover
from apps.moderation.models import MessageReportCase, ModerationPaymentAction
from apps.moderation.services.payment_actions import process_payment_action
from apps.moderation.services.report_cases import remove_case
from apps.payments.models import PaymentCapture
from apps.schools.models import Competition, Entity

from .models import EmailOutbox
from .services.outbox import process_email_outbox_item, process_pending_email_outbox
from .services.providers import (
    DeliveryResult,
    EmailMessage,
    EmailProviderError,
    ResendEmailProvider,
)


class RecordingProvider:
    def __init__(self, *, result=None, error=None):
        self.result = result or DeliveryResult(provider_message_id="email_test_123")
        self.error = error
        self.calls = []

    def send(self, message, *, idempotency_key):
        self.calls.append((message, idempotency_key))
        if self.error:
            raise self.error
        return self.result


class EmailOutboxTests(TestCase):
    def setUp(self):
        self.competition = Competition.objects.get(
            name="College Football", slug="college-football", sport="Football"
        )
        self.school = Entity.objects.create(
            competition=self.competition,
            name="Oklahoma",
            slug="oklahoma-notifications",
            short_name="Oklahoma",
            group_name="SEC",
            accent_color="#841617",
        )
        self.board = Board.objects.create(entity=self.school)
        self.profile = UserProfile.objects.create(
            cognito_sub="notifications-customer",
            email="customer@example.com",
            display_name="NotificationFan",
        )
        self.bid = Bid.objects.create(
            board=self.board,
            bidder=self.profile,
            represented_entity=self.school,
            message="A message that must never enter email logs.",
            amount_cents=500,
            status=Bid.Status.WON,
            stripe_payment_intent_id="pi_should_not_enter_email_context",
        )
        self.takeover = BoardTakeover.objects.create(
            board=self.board,
            bid=self.bid,
            controller=self.profile,
            controller_display_name=self.profile.display_name,
            represented_entity=self.school,
            message=self.bid.message,
            amount_cents=self.bid.amount_cents,
        )
        self.board.current_bid = self.bid
        self.board.current_controller = self.profile
        self.board.current_amount_cents = self.bid.amount_cents
        self.board.current_message = self.bid.message
        self.board.save()

    def test_removal_creates_one_notice_without_message_or_payment_identifiers(self):
        case = MessageReportCase.objects.create(
            takeover=self.takeover,
            last_reported_at=timezone.now(),
        )
        actor = get_user_model().objects.create_user(username="notification-moderator")

        remove_case(case_id=case.id, actor=actor, reason="Guideline violation.")
        remove_case(case_id=case.id, actor=actor, reason="Duplicate retry.")

        outbox = EmailOutbox.objects.get(kind=EmailOutbox.Kind.MESSAGE_REMOVED)
        self.assertEqual(EmailOutbox.objects.filter(event_key=outbox.event_key).count(), 1)
        self.assertTrue(outbox.waiting_for_refund)
        self.assertNotIn(self.bid.message, outbox.context)
        self.assertNotIn("pi_should_not_enter_email_context", str(outbox.context))
        self.assertEqual(outbox.recipient_email, self.profile.email)

    def test_successful_refund_creates_one_confirmation_after_payment_state_commits(self):
        PaymentCapture.objects.create(
            bid=self.bid,
            stripe_payment_intent_id=self.bid.stripe_payment_intent_id,
            stripe_charge_id="ch_notifications",
            stripe_balance_transaction_id="txn_notifications",
            gross_amount_cents=self.bid.amount_cents,
            currency="usd",
            stripe_fee_cents=42,
            net_amount_cents=self.bid.amount_cents - 42,
            fee_status=PaymentCapture.FeeStatus.AVAILABLE,
        )
        case = MessageReportCase.objects.create(
            takeover=self.takeover,
            last_reported_at=timezone.now(),
        )
        actor = get_user_model().objects.create_user(username="refund-moderator")
        remove_case(case_id=case.id, actor=actor, reason="Guideline violation.")
        action = case.payment_actions.get(operation=ModerationPaymentAction.Operation.REFUND)

        with patch("apps.moderation.services.payment_actions.refund_payment", return_value="re_notifications"):
            self.assertTrue(process_payment_action(action.id))
            self.assertTrue(process_payment_action(action.id))

        notices = EmailOutbox.objects.filter(kind=EmailOutbox.Kind.MESSAGE_REMOVED)
        self.assertEqual(notices.count(), 1)
        notice = notices.get()
        self.assertFalse(notice.waiting_for_refund)
        self.assertEqual(notice.context["amount_paid"], "$5.00")
        self.assertEqual(notice.context["processing_fee"], "$0.42")
        self.assertEqual(notice.context["refund_amount"], "$4.58")
        self.assertFalse(EmailOutbox.objects.filter(kind=EmailOutbox.Kind.REFUND_CONFIRMATION).exists())

        provider = RecordingProvider()
        self.assertTrue(process_email_outbox_item(notice.id, provider=provider))
        delivered_message = provider.calls[0][0]
        self.assertIn("message you published", delivered_message.text_body)
        self.assertIn("Amount paid: $5.00", delivered_message.text_body)
        self.assertIn("Stripe processing fee: $0.42", delivered_message.text_body)
        self.assertIn("Refund issued: $4.58", delivered_message.text_body)

    @override_settings(TAKEBOARD_EMAIL_ENABLED=True)
    def test_removal_notice_waits_for_refund_before_delivery(self):
        case = MessageReportCase.objects.create(
            takeover=self.takeover,
            last_reported_at=timezone.now(),
        )
        actor = get_user_model().objects.create_user(username="waiting-refund-moderator")

        remove_case(case_id=case.id, actor=actor, reason="Guideline violation.")
        provider = RecordingProvider()

        self.assertEqual(process_pending_email_outbox(provider=provider), 0)
        outbox = EmailOutbox.objects.get(kind=EmailOutbox.Kind.MESSAGE_REMOVED)
        self.assertEqual(outbox.status, EmailOutbox.Status.PENDING)
        self.assertTrue(outbox.waiting_for_refund)
        self.assertEqual(provider.calls, [])

    @override_settings(TAKEBOARD_EMAIL_ENABLED=False)
    def test_disabled_delivery_does_not_claim_pending_outbox(self):
        outbox = EmailOutbox.objects.create(
            event_key="test-disabled-delivery",
            kind=EmailOutbox.Kind.REFUND_CONFIRMATION,
            recipient_email=self.profile.email,
            context={
                "board_name": "Oklahoma",
                "refund_amount": "$4.58",
                "refunded_on": "September 2, 2026",
                "reference": "TTB-TEST",
                "policy_url": "http://localhost:8000/refunds/",
                "support_url": "http://localhost:8000/contact/",
                "support_email": "support@example.com",
            },
        )

        self.assertEqual(process_pending_email_outbox(), 0)
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.PENDING)
        self.assertEqual(outbox.attempts, 0)

    @override_settings(TAKEBOARD_EMAIL_ENABLED=True)
    def test_provider_failure_is_retryable_and_success_reuses_stable_key(self):
        outbox = EmailOutbox.objects.create(
            event_key="test-retryable-delivery",
            kind=EmailOutbox.Kind.MESSAGE_REMOVED,
            recipient_email=self.profile.email,
            context={
                "board_name": "Oklahoma",
                "removed_on": "September 2, 2026",
                "reference": "TTB-TEST",
                "policy_url": "http://localhost:8000/community-guidelines/",
                "support_url": "http://localhost:8000/contact/",
                "support_email": "support@example.com",
            },
        )
        failing = RecordingProvider(error=EmailProviderError("provider_timeout"))

        self.assertFalse(process_email_outbox_item(outbox.id, provider=failing))
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.FAILED)
        self.assertEqual(outbox.last_error_code, "provider_timeout")
        self.assertEqual(outbox.attempts, 1)
        self.assertGreater(outbox.available_at, timezone.now())

        outbox.available_at = timezone.now() - timedelta(seconds=1)
        outbox.save(update_fields=["available_at"])
        succeeding = RecordingProvider()
        self.assertTrue(process_email_outbox_item(outbox.id, provider=succeeding))
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.SENT)
        self.assertEqual(outbox.provider_message_id, "email_test_123")
        self.assertEqual(succeeding.calls[0][1], "test-retryable-delivery")

    @override_settings(TAKEBOARD_EMAIL_ENABLED=True, TAKEBOARD_EMAIL_PROCESSING_TIMEOUT_SECONDS=60)
    def test_stale_processing_lease_is_reclaimed(self):
        outbox = EmailOutbox.objects.create(
            event_key="test-stale-lease",
            kind=EmailOutbox.Kind.REFUND_CONFIRMATION,
            recipient_email=self.profile.email,
            context={
                "board_name": "Oklahoma",
                "refund_amount": "$4.58",
                "refunded_on": "September 2, 2026",
                "reference": "TTB-TEST",
                "policy_url": "http://localhost:8000/refunds/",
                "support_url": "http://localhost:8000/contact/",
                "support_email": "support@example.com",
            },
            status=EmailOutbox.Status.PROCESSING,
            locked_at=timezone.now() - timedelta(minutes=10),
            attempts=1,
        )
        provider = RecordingProvider()

        self.assertTrue(process_email_outbox_item(outbox.id, provider=provider))
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.SENT)
        self.assertEqual(outbox.attempts, 2)

    @override_settings(TAKEBOARD_EMAIL_ENABLED=True, TAKEBOARD_EMAIL_PROVIDER="noop")
    def test_noop_provider_marks_delivery_suppressed_without_network_call(self):
        outbox = EmailOutbox.objects.create(
            event_key="test-noop-delivery",
            kind=EmailOutbox.Kind.MESSAGE_REMOVED,
            recipient_email=self.profile.email,
            context={
                "board_name": "Oklahoma",
                "removed_on": "September 2, 2026",
                "reference": "TTB-TEST",
                "policy_url": "http://localhost:8000/community-guidelines/",
                "support_url": "http://localhost:8000/contact/",
                "support_email": "support@example.com",
            },
        )

        with patch("apps.notifications.services.providers.urlopen") as urlopen:
            self.assertFalse(process_email_outbox_item(outbox.id))

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.SUPPRESSED)
        urlopen.assert_not_called()

    @override_settings(
        TAKEBOARD_EMAIL_FROM="Take the Board <notifications@example.com>",
        TAKEBOARD_EMAIL_PROVIDER_TIMEOUT_SECONDS=4,
    )
    def test_resend_adapter_passes_stable_idempotency_key_without_real_network(self):
        provider = ResendEmailProvider(
            api_key="re_test_key",
            api_url="https://api.resend.test/emails",
            timeout_seconds=4,
        )
        response = type(
            "Response",
            (),
            {"status": 200, "read": lambda self, size: b'{"id":"re_test"}'},
        )()

        with patch("apps.notifications.services.providers.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = response
            result = provider.send(
                EmailMessage(
                    subject="Test",
                    text_body="Test body",
                    html_body="<p>Test body</p>",
                    recipient_email="customer@example.com",
                ),
                idempotency_key="message-removed-v1:test",
            )

        self.assertEqual(result.provider_message_id, "re_test")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Idempotency-key"), "message-removed-v1:test")
        self.assertEqual(request.get_header("Authorization"), "Bearer re_test_key")
        self.assertEqual(request.get_header("User-agent"), "take-the-board/1.0")
