from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib import admin
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.accounts.services.session import AUTH_SESSION_KEY
from apps.bidding.models import Bid
from apps.boards.models import Board, BoardTakeover
from apps.moderation.models import MessageReport, MessageReportCase, ModerationPaymentAction
from apps.moderation.admin import MessageReportCaseAdmin
from apps.moderation.services.payment_actions import process_payment_action
from apps.moderation.services.report_cases import remove_case
from apps.payments.models import LedgerEntry, PaymentCapture
from apps.schools.models import School


class MessageReportingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.school = School.objects.create(
            name="Oklahoma", slug="oklahoma", short_name="Oklahoma", conference="SEC", accent_color="#841617"
        )
        self.board = Board.objects.create(school=self.school)
        self.author = self.profile("author", "Author")
        self.reporter = self.profile("reporter", "Reporter")
        self.takeover, self.bid = self.publish("A safe published message.")

    def profile(self, subject, display_name):
        return UserProfile.objects.create(
            cognito_sub=f"reporting-{subject}",
            email=f"{subject}@example.com",
            display_name=display_name,
        )

    def publish(self, message, *, previous_bid=None, amount=500):
        bid = Bid.objects.create(
            board=self.board,
            bidder=self.author,
            represented_school=self.school,
            message=message,
            amount_cents=amount,
            status=Bid.Status.DEMO_WON,
        )
        takeover = BoardTakeover.objects.create(
            board=self.board,
            bid=bid,
            previous_bid=previous_bid,
            controller=self.author,
            controller_display_name=self.author.display_name,
            represented_school=self.school,
            message=message,
            amount_cents=amount,
        )
        self.board.current_bid = bid
        self.board.current_controller = self.author
        self.board.current_amount_cents = amount
        self.board.current_message = message
        self.board.save()
        return takeover, bid

    def authenticated_client(self, profile=None, csrf=False):
        client = Client(enforce_csrf_checks=csrf)
        session = client.session
        profile = profile or self.reporter
        session[AUTH_SESSION_KEY] = {
            "profile_id": profile.id,
            "cognito_sub": profile.cognito_sub,
            "expires_at": (timezone.now() + timedelta(hours=1)).timestamp(),
        }
        session.save()
        if csrf:
            client.cookies["csrftoken"] = "a" * 32
        return client

    def report_url(self):
        return reverse("boards:report_takeover", kwargs={"takeover_public_id": self.takeover.public_id})

    def test_authenticated_report_creates_case_and_immutable_submission(self):
        response = self.authenticated_client().post(
            self.report_url(),
            {"category": MessageReport.Category.HATE_SPEECH},
        )

        self.assertRedirects(response, reverse("boards:index"))
        report_case = MessageReportCase.objects.get(takeover=self.takeover)
        self.assertEqual(report_case.status, MessageReportCase.Status.OPEN)
        self.assertEqual(report_case.reports.count(), 1)
        self.assertEqual(report_case.reports.get().reporter, self.reporter)

    def test_live_report_button_targets_the_rendered_dialog(self):
        response = self.authenticated_client().get(
            reverse("schools:detail", kwargs={"slug": self.school.slug})
        )

        modal_id = f"report-modal-current-{self.takeover.public_id}"
        self.assertContains(response, f'data-open-dialog="{modal_id}"')
        self.assertContains(response, f'id="{modal_id}"')

    @override_settings(TAKEBOARD_AUTH_MODAL_PREVIEW=True)
    def test_signed_out_fan_can_open_the_sign_in_flow_from_a_report_button(self):
        response = self.client.get(reverse("schools:detail", kwargs={"slug": self.school.slug}))

        self.assertContains(response, 'data-open-dialog="auth-modal"')
        self.assertContains(response, "Sign in to report this message.")
        self.assertContains(response, "You need to be signed in to report a public board message.")

    def test_approved_case_keeps_the_report_button_and_shows_review_message(self):
        MessageReportCase.objects.create(
            takeover=self.takeover,
            status=MessageReportCase.Status.APPROVED,
            last_reported_at=timezone.now(),
            resolved_at=timezone.now(),
            resolution_reason="Reviewed and approved.",
        )

        response = self.authenticated_client().get(
            reverse("schools:detail", kwargs={"slug": self.school.slug})
        )

        modal_id = f"report-modal-current-{self.takeover.public_id}"
        self.assertContains(response, f'data-open-dialog="{modal_id}"')
        self.assertContains(response, f'id="{modal_id}"')
        self.assertContains(
            response,
            "This message has already been reported and reviewed as acceptable under our community guidelines.",
        )

    def test_case_admin_shows_the_message_and_bid_payment_context(self):
        self.bid.stripe_payment_intent_id = "pi_reporting_test"
        self.bid.save(update_fields=["stripe_payment_intent_id"])
        report_case = MessageReportCase.objects.create(takeover=self.takeover, last_reported_at=timezone.now())
        model_admin = MessageReportCaseAdmin(MessageReportCase, admin.site)

        self.assertIn(self.takeover.message, str(model_admin.reported_message(report_case)))
        payment_context = str(model_admin.payment_context(report_case))
        self.assertIn("pi_reporting_test", payment_context)
        self.assertIn(str(self.bid.public_id), payment_context)

    def test_csrf_and_duplicate_submissions_are_safe(self):
        csrf_client = self.authenticated_client(csrf=True)
        response = csrf_client.post(self.report_url(), {"category": MessageReport.Category.SPAM})
        self.assertEqual(response.status_code, 403)

        response = csrf_client.post(
            self.report_url(),
            {"category": MessageReport.Category.SPAM},
            HTTP_X_CSRFTOKEN="a" * 32,
        )
        self.assertEqual(response.status_code, 302)
        response = csrf_client.post(
            self.report_url(),
            {"category": MessageReport.Category.SPAM},
            HTTP_X_CSRFTOKEN="a" * 32,
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, "no longer accepting reports")
        self.assertEqual(MessageReport.objects.count(), 1)

    def test_closed_and_invalid_targets_do_not_write(self):
        report_case = MessageReportCase.objects.create(
            takeover=self.takeover,
            status=MessageReportCase.Status.APPROVED,
            last_reported_at=timezone.now(),
            resolved_at=timezone.now(),
            resolution_reason="Reviewed and allowed.",
        )
        response = self.authenticated_client().post(
            self.report_url(), {"category": MessageReport.Category.SPAM}, HTTP_HX_REQUEST="true"
        )
        self.assertContains(response, "no longer accepting reports")
        self.assertEqual(report_case.reports.count(), 0)

        response = self.authenticated_client().post(
            self.report_url(), {"category": "free_form_explanation"}, HTTP_HX_REQUEST="true"
        )
        self.assertContains(response, "no longer accepting reports")
        self.assertEqual(MessageReport.objects.count(), 0)

    def test_remove_current_takeover_restores_prior_and_cancels_pending(self):
        first_takeover, first_bid = self.takeover, self.bid
        second_takeover, second_bid = self.publish(
            "Second message.", previous_bid=first_bid, amount=600
        )
        pending = Bid.objects.create(
            board=self.board,
            bidder=self.reporter,
            represented_school=self.school,
            message="Pending message.",
            amount_cents=700,
            status=Bid.Status.AUTHORIZED,
        )
        self.board.pending_bid = pending
        self.board.save(update_fields=["pending_bid"])
        report_case = MessageReportCase.objects.create(takeover=second_takeover, last_reported_at=timezone.now())
        actor = get_user_model().objects.create_user(username="moderator")

        result = remove_case(case_id=report_case.id, actor=actor, reason="Violates community guidelines.")

        self.assertTrue(result.changed)
        self.assertTrue(result.restored_previous)
        self.board.refresh_from_db()
        report_case.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(self.board.current_bid_id, first_bid.id)
        self.assertEqual(self.board.current_message, first_takeover.message)
        self.assertIsNone(self.board.pending_bid_id)
        self.assertEqual(pending.status, Bid.Status.AUTH_CANCELED)
        self.assertEqual(report_case.status, MessageReportCase.Status.REMOVED)
        self.assertEqual(report_case.payment_actions.count(), 2)

    def test_removal_of_captured_bid_refunds_once_after_provider_success(self):
        self.bid.status = Bid.Status.WON
        self.bid.stripe_payment_intent_id = "pi_test"
        self.bid.save(update_fields=["status", "stripe_payment_intent_id"])
        PaymentCapture.objects.create(
            bid=self.bid,
            stripe_payment_intent_id="pi_test",
            stripe_charge_id="ch_test",
            stripe_balance_transaction_id="txn_test",
            gross_amount_cents=self.bid.amount_cents,
            currency="usd",
            stripe_fee_cents=42,
            net_amount_cents=self.bid.amount_cents - 42,
            fee_status=PaymentCapture.FeeStatus.AVAILABLE,
        )
        report_case = MessageReportCase.objects.create(takeover=self.takeover, last_reported_at=timezone.now())
        actor = get_user_model().objects.create_user(username="payments-moderator")
        remove_case(case_id=report_case.id, actor=actor, reason="Upheld report.")
        action = report_case.payment_actions.get(bid=self.bid)

        with patch("apps.moderation.services.payment_actions.refund_payment", return_value="re_test") as refund:
            self.assertTrue(process_payment_action(action.id))
            self.assertTrue(process_payment_action(action.id))

        self.bid.refresh_from_db()
        action.refresh_from_db()
        self.assertEqual(self.bid.status, Bid.Status.REFUNDED)
        self.assertEqual(action.status, ModerationPaymentAction.Status.SUCCEEDED)
        self.assertEqual(action.amount_cents, self.bid.amount_cents - 42)
        self.assertEqual(LedgerEntry.objects.filter(type=LedgerEntry.Type.REFUND, bid=self.bid).count(), 1)
        self.assertEqual(
            LedgerEntry.objects.get(type=LedgerEntry.Type.REFUND, bid=self.bid).amount_cents,
            -(self.bid.amount_cents - 42),
        )
        refund.assert_called_once_with(
            bid=self.bid,
            amount_cents=self.bid.amount_cents - 42,
            idempotency_key=f"takeboard-moderation-refund-{report_case.public_id}",
        )

    def test_captured_removal_waits_for_actual_stripe_fee_before_refunding(self):
        self.bid.status = Bid.Status.WON
        self.bid.stripe_payment_intent_id = "pi_pending_fee"
        self.bid.save(update_fields=["status", "stripe_payment_intent_id"])
        PaymentCapture.objects.create(
            bid=self.bid,
            stripe_payment_intent_id="pi_pending_fee",
            gross_amount_cents=self.bid.amount_cents,
            currency="usd",
        )
        report_case = MessageReportCase.objects.create(takeover=self.takeover, last_reported_at=timezone.now())
        actor = get_user_model().objects.create_user(username="pending-fee-moderator")
        remove_case(case_id=report_case.id, actor=actor, reason="Upheld report.")
        action = report_case.payment_actions.get(bid=self.bid)

        with patch("apps.moderation.services.payment_actions.refund_payment") as refund:
            self.assertFalse(process_payment_action(action.id))

        action.refresh_from_db()
        self.bid.refresh_from_db()
        self.assertEqual(action.status, ModerationPaymentAction.Status.PENDING)
        self.assertIsNone(action.amount_cents)
        self.assertEqual(action.last_error_code, "stripe_fee_data_pending")
        self.assertEqual(self.bid.status, Bid.Status.WON)
        refund.assert_not_called()
