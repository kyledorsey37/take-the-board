import json
from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.accounts.services.session import AUTH_SESSION_KEY
from apps.bidding.models import Bid
from apps.bidding.services.create_bid import TakeoverError
from apps.bidding.services.finalize_bid import finalize_due_board
from apps.bidding.services.rules import current_board_rules
from apps.boards.models import Board
from apps.core.models import GameConfig
from apps.schools.models import School

from .models import StripeEvent
from .services.create_checkout import create_checkout
from .services.process_webhooks import process_pending_stripe_events


@override_settings(STRIPE_WEBHOOK_SECRET="whsec_test")
class StripeWebhookTests(TestCase):
    def setUp(self) -> None:
        self.payload = {
            "id": "evt_test_123",
            "object": "event",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test_123"}},
        }
        self.raw_payload = json.dumps(self.payload).encode("utf-8")

    @patch("apps.payments.views.stripe.Webhook.construct_event")
    def test_webhook_verifies_and_stores_a_new_event(self, construct_event) -> None:
        construct_event.return_value = self.payload

        response = self.client.post(
            reverse("payments:stripe_webhook"),
            data=self.raw_payload,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="valid-signature",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"received": True})
        event = StripeEvent.objects.get(event_id="evt_test_123")
        self.assertEqual(event.event_type, "checkout.session.completed")
        self.assertEqual(event.payload, self.payload)
        construct_event.assert_called_once_with(
            self.raw_payload,
            "valid-signature",
            "whsec_test",
        )

    @patch("apps.payments.views.stripe.Webhook.construct_event")
    def test_duplicate_event_is_acknowledged_without_a_second_record(self, construct_event) -> None:
        construct_event.return_value = self.payload

        url = reverse("payments:stripe_webhook")
        first_response = self.client.post(
            url,
            data=self.raw_payload,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="valid-signature",
        )
        second_response = self.client.post(
            url,
            data=self.raw_payload,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="valid-signature",
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.json(), {"received": True, "duplicate": True})
        self.assertEqual(StripeEvent.objects.filter(event_id="evt_test_123").count(), 1)

    @patch("apps.payments.views.stripe.Webhook.construct_event")
    def test_invalid_signature_is_rejected(self, construct_event) -> None:
        construct_event.side_effect = ValueError("invalid signature")

        response = self.client.post(
            reverse("payments:stripe_webhook"),
            data=self.raw_payload,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="invalid-signature",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(StripeEvent.objects.count(), 0)

    @patch("apps.payments.views.stripe.Webhook.construct_event")
    def test_webhook_is_exempt_from_browser_csrf(self, construct_event) -> None:
        construct_event.return_value = self.payload
        csrf_client = Client(enforce_csrf_checks=True)

        response = csrf_client.post(
            reverse("payments:stripe_webhook"),
            data=self.raw_payload,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="valid-signature",
        )

        self.assertEqual(response.status_code, 200)


@override_settings(
    STRIPE_SECRET_KEY="sk_test_example",
    TAKEBOARD_STRIPE_ENABLED=True,
    TAKEBOARD_REQUIRE_AUTH_FOR_BIDDING=True,
)
class StripeBidFlowTests(TestCase):
    def setUp(self) -> None:
        GameConfig.objects.create()
        self.school = School.objects.create(
            name="Oklahoma",
            slug="oklahoma",
            short_name="Oklahoma",
            conference="SEC",
            accent_color="#841617",
        )
        self.represented_school = School.objects.create(
            name="Texas",
            slug="texas",
            short_name="Texas",
            conference="SEC",
            accent_color="#BF5700",
        )
        self.board = Board.objects.create(school=self.school)
        self.profile = UserProfile.objects.create(
            cognito_sub="stripe-test-subject",
            email="fan@example.com",
            display_name="StripeFan",
        )

    @patch("apps.payments.services.create_checkout.stripe.checkout.Session.create")
    def test_checkout_uses_the_server_side_bid_amount_and_manual_capture(self, create_session) -> None:
        create_session.return_value = {
            "id": "cs_test_123",
            "client_secret": "cs_secret_123",
            "payment_intent": None,
        }

        result = create_checkout(
            board_id=self.board.id,
            profile_id=self.profile.id,
            represented_school_id=self.represented_school.id,
            amount=Decimal("17.00"),
            message="TAKE THE BOARD.",
            rules=current_board_rules(),
            return_url="http://testserver/schools/oklahoma/?checkout_session_id={CHECKOUT_SESSION_ID}",
        )

        bid = Bid.objects.get(pk=result.bid_id)
        self.assertEqual(result.client_secret, "cs_secret_123")
        self.assertEqual(bid.amount_cents, 1700)
        self.assertEqual(bid.status, Bid.Status.CHECKOUT_CREATED)
        self.assertEqual(bid.stripe_checkout_session_id, "cs_test_123")
        call = create_session.call_args
        self.assertEqual(call.kwargs["mode"], "payment")
        self.assertEqual(call.kwargs["ui_mode"], "embedded")
        self.assertNotIn("payment_method_types", call.kwargs)
        self.assertEqual(call.kwargs["managed_payments"], {"enabled": False})
        self.assertEqual(call.kwargs["payment_intent_data"]["capture_method"], "manual")
        self.assertEqual(call.kwargs["line_items"][0]["price_data"]["unit_amount"], 1700)
        self.assertEqual(call.kwargs["idempotency_key"], f"takeboard-checkout-{bid.public_id}")

    @patch("apps.payments.services.create_checkout.stripe.checkout.Session.create")
    def test_checkout_rejects_fractional_dollars_before_stripe(self, create_session) -> None:
        with self.assertRaisesRegex(TakeoverError, "Use whole dollar amounts"):
            create_checkout(
                board_id=self.board.id,
                profile_id=self.profile.id,
                represented_school_id=self.represented_school.id,
                amount=Decimal("17.01"),
                message="TAKE THE BOARD.",
                rules=current_board_rules(),
                return_url="http://testserver/schools/oklahoma/?checkout_session_id={CHECKOUT_SESSION_ID}",
            )

        create_session.assert_not_called()

    @patch("apps.payments.services.create_checkout.stripe.checkout.Session.create")
    def test_bid_endpoint_returns_embedded_checkout_instead_of_publishing(self, create_session) -> None:
        create_session.return_value = {
            "id": "cs_test_123",
            "client_secret": "cs_secret_123",
            "payment_intent": None,
        }
        session = self.client.session
        session[AUTH_SESSION_KEY] = {
            "profile_id": self.profile.id,
            "cognito_sub": self.profile.cognito_sub,
            "expires_at": 4_000_000_000,
        }
        session.save()

        response = self.client.post(
            reverse("bidding:take"),
            {
                "board_slug": "oklahoma",
                "represented_school": self.represented_school.id,
                "amount": "17.00",
                "message": "TAKE THE BOARD.",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-stripe-checkout")
        self.assertContains(response, "cs_secret_123")
        bid = Bid.objects.get()
        self.assertContains(response, f"/api/payments/bids/{bid.public_id}/status/")
        self.assertEqual(bid.status, Bid.Status.CHECKOUT_CREATED)
        self.board.refresh_from_db()
        self.assertIsNone(self.board.current_bid_id)

    def test_bid_status_is_visible_only_to_the_authenticated_bidder(self) -> None:
        bid = Bid.objects.create(
            board=self.board,
            bidder=self.profile,
            represented_school=self.represented_school,
            message="TAKE THE BOARD.",
            amount_cents=1700,
            status=Bid.Status.CHECKOUT_CREATED,
        )
        session = self.client.session
        session[AUTH_SESSION_KEY] = {
            "profile_id": self.profile.id,
            "cognito_sub": self.profile.cognito_sub,
            "expires_at": 4_000_000_000,
        }
        session.save()

        response = self.client.get(reverse("payments:bid_status", kwargs={"public_id": bid.public_id}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], Bid.Status.CHECKOUT_CREATED)
        self.assertEqual(response.json()["board_url"], "/schools/oklahoma/")

    def test_authorization_event_makes_the_bid_the_only_pending_challenger(self) -> None:
        bid = Bid.objects.create(
            board=self.board,
            bidder=self.profile,
            represented_school=self.represented_school,
            message="TAKE THE BOARD.",
            amount_cents=100,
            status=Bid.Status.CHECKOUT_CREATED,
            stripe_checkout_session_id="cs_test_123",
        )
        StripeEvent.objects.create(
            event_id="evt_authorized_123",
            event_type="payment_intent.amount_capturable_updated",
            payload={
                "id": "evt_authorized_123",
                "type": "payment_intent.amount_capturable_updated",
                "data": {
                    "object": {
                        "id": "pi_test_123",
                        "metadata": {"bid_id": str(bid.public_id)},
                    }
                },
            },
        )

        self.assertEqual(process_pending_stripe_events(), 1)
        bid.refresh_from_db()
        self.board.refresh_from_db()
        self.assertEqual(bid.status, Bid.Status.AUTHORIZED)
        self.assertEqual(bid.stripe_payment_intent_id, "pi_test_123")
        self.assertEqual(self.board.pending_bid_id, bid.id)

    def test_successful_capture_publishes_a_stripe_bid(self) -> None:
        bid = Bid.objects.create(
            board=self.board,
            bidder=self.profile,
            represented_school=self.represented_school,
            message="TAKE THE BOARD.",
            amount_cents=100,
            status=Bid.Status.AUTHORIZED,
            stripe_payment_intent_id="pi_test_123",
            authorized_at=timezone.now(),
        )
        self.board.pending_bid = bid
        self.board.save(update_fields=["pending_bid"])

        result = finalize_due_board(
            board_id=self.board.id,
            rules=current_board_rules(),
            capture_pending_bid=lambda pending_bid: pending_bid.id == bid.id,
        )

        self.assertTrue(result.published)
        bid.refresh_from_db()
        self.assertEqual(bid.status, Bid.Status.WON)
