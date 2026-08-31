import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache

from apps.accounts.models import UserProfile
from apps.accounts.services.session import AUTH_SESSION_KEY
from apps.bidding.models import Bid, BidConfirmation
from apps.bidding.services.confirmation import create_confirmation
from apps.bidding.services.create_bid import TakeoverError
from apps.bidding.services.finalize_bid import finalize_due_board
from apps.bidding.services.rules import current_board_rules
from apps.boards.models import Board
from apps.core.models import GameConfig
from apps.moderation.models import MessageValidation
from apps.moderation.services.nova_classifier import Classification
from apps.moderation.services.rate_limits import safe_key
from apps.moderation.services.validators import validate_message_deterministically
from apps.schools.models import Competition, Entity

from .models import LedgerEntry, PaymentCapture, PurchaseEvidence, StripeEvent
from .services.capture_payment import capture_payment
from .services.create_checkout import create_checkout
from .services.evidence import record_purchase_evidence
from .services.process_webhooks import process_pending_stripe_events


@override_settings(STRIPE_WEBHOOK_SECRET="whsec_test")
class StripeWebhookTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
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
        cache.clear()
        GameConfig.objects.create()
        self.competition = Competition.objects.get(
            name="College Football", slug="college-football", sport="Football"
        )
        self.school = Entity.objects.create(
            competition=self.competition,
            name="Oklahoma",
            slug="oklahoma",
            short_name="Oklahoma",
            group_name="SEC",
            accent_color="#841617",
        )
        self.represented_entity = Entity.objects.create(
            competition=self.competition,
            name="Texas",
            slug="texas",
            short_name="Texas",
            group_name="SEC",
            accent_color="#BF5700",
        )
        self.board = Board.objects.create(entity=self.school)
        self.profile = UserProfile.objects.create(
            cognito_sub="stripe-test-subject",
            email="fan@example.com",
            display_name="StripeFan",
            age_acknowledgement_version="18-plus-v1",
            age_acknowledged_at=timezone.now(),
        )

    def approved_validation(self, message: str = "TAKE THE BOARD.") -> MessageValidation:
        candidate = validate_message_deterministically(message)
        return MessageValidation.objects.create(
            user=self.profile,
            board=self.board,
            represented_entity=self.represented_entity,
            message=message,
            message_hash=safe_key("message-value", candidate.original),
            decision=MessageValidation.Decision.ALLOW,
            category="safe",
            confidence="0.9900",
            policy_version=settings.TAKEBOARD_MODERATION_POLICY_VERSION,
            classifier_version=settings.TAKEBOARD_MODERATION_CLASSIFIER_MODEL_VERSION,
            expires_at=timezone.now() + timedelta(minutes=10),
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
            represented_entity_id=self.represented_entity.id,
            amount=Decimal("17.00"),
            message="TAKE THE BOARD.",
            validation_id=self.approved_validation().id,
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
        self.assertEqual(call.kwargs["payment_intent_data"]["statement_descriptor"], "TAKETHEBOARD")
        self.assertEqual(call.kwargs["line_items"][0]["price_data"]["unit_amount"], 1700)
        self.assertEqual(call.kwargs["idempotency_key"], f"takeboard-checkout-{bid.public_id}")

    @patch("apps.payments.services.create_checkout.stripe.checkout.Session.create")
    def test_checkout_rejects_fractional_dollars_before_stripe(self, create_session) -> None:
        with self.assertRaisesRegex(TakeoverError, "Use whole dollar amounts"):
            create_checkout(
                board_id=self.board.id,
                profile_id=self.profile.id,
                represented_entity_id=self.represented_entity.id,
                amount=Decimal("17.01"),
                message="TAKE THE BOARD.",
                validation_id=self.approved_validation().id,
                rules=current_board_rules(),
                return_url="http://testserver/schools/oklahoma/?checkout_session_id={CHECKOUT_SESSION_ID}",
            )

        create_session.assert_not_called()

    @patch("apps.payments.services.create_checkout.stripe.checkout.Session.create")
    def test_checkout_requires_a_fresh_matching_one_time_validation(self, create_session) -> None:
        validation = self.approved_validation()
        base_kwargs = {
            "board_id": self.board.id,
            "profile_id": self.profile.id,
            "represented_entity_id": self.represented_entity.id,
            "amount": Decimal("17.00"),
            "message": "TAKE THE BOARD.",
            "rules": current_board_rules(),
            "return_url": "http://testserver/return/?checkout_session_id={CHECKOUT_SESSION_ID}",
        }
        with self.assertRaisesRegex(TakeoverError, "fresh message approval"):
            create_checkout(**base_kwargs, validation_id=999999)
        with self.assertRaisesRegex(TakeoverError, "fresh message approval"):
            create_checkout(
                **{**base_kwargs, "message": "Different message."},
                validation_id=validation.id,
            )
        validation.expires_at = timezone.now() - timedelta(seconds=1)
        validation.save(update_fields=["expires_at"])
        with self.assertRaisesRegex(TakeoverError, "fresh message approval"):
            create_checkout(**base_kwargs, validation_id=validation.id)
        create_session.assert_not_called()

    @patch("apps.payments.services.create_checkout.stripe.checkout.Session.create")
    def test_bid_endpoint_requires_confirmation_before_returning_checkout(self, create_session) -> None:
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

        with patch(
            "apps.moderation.services.validation.classify_message",
            return_value=Classification("allow", "safe", 0.99),
        ):
            response = self.client.post(
                reverse("bidding:take"),
                {
                    "board_slug": "oklahoma",
                    "represented_entity": self.represented_entity.id,
                    "amount": "17.00",
                    "message": "TAKE THE BOARD.",
                },
                HTTP_HX_REQUEST="true",
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Review your bid")
        self.assertContains(response, "Continue to payment")
        self.assertContains(response, "Edit bid")
        self.assertNotContains(response, "real-money purchase")
        self.assertNotContains(response, "terms_accepted")
        self.assertEqual(Bid.objects.count(), 0)
        confirmation = BidConfirmation.objects.get()
        response = self.client.post(
            reverse("bidding:confirm", kwargs={"public_id": confirmation.public_id}),
            {},
            HTTP_HX_REQUEST="true",
        )

        self.assertContains(response, "data-stripe-checkout")
        self.assertContains(response, "cs_secret_123")
        self.assertContains(response, 'aria-label="Close checkout"')
        bid = Bid.objects.get()
        self.assertContains(response, f"/api/payments/bids/{bid.public_id}/status/")
        self.assertEqual(bid.status, Bid.Status.CHECKOUT_CREATED)
        self.board.refresh_from_db()
        self.assertIsNone(self.board.current_bid_id)

    def test_first_paid_bid_requires_18_plus_acknowledgement_once(self) -> None:
        self.profile.age_acknowledgement_version = ""
        self.profile.age_acknowledged_at = None
        self.profile.save(update_fields=["age_acknowledgement_version", "age_acknowledged_at"])
        session = self.client.session
        session[AUTH_SESSION_KEY] = {
            "profile_id": self.profile.id,
            "cognito_sub": self.profile.cognito_sub,
            "expires_at": 4_000_000_000,
        }
        session.save()

        response = self.client.get(reverse("schools:detail", kwargs={"slug": "oklahoma"}))

        self.assertContains(response, "I confirm that I am 18 or older")
        self.assertNotContains(response, "You’ll only see this once")
        self.assertNotContains(response, "purchase record")
        with patch(
            "apps.moderation.services.validation.classify_message",
            return_value=__import__(
                "apps.moderation.services.nova_classifier", fromlist=["Classification"]
            ).Classification("allow", "safe", 0.99),
        ):
            response = self.client.post(
                reverse("bidding:take"),
                {
                    "board_slug": "oklahoma",
                    "represented_entity": self.represented_entity.id,
                    "amount": "17.00",
                    "message": "TAKE THE BOARD.",
                },
                HTTP_HX_REQUEST="true",
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "18 or older")
        self.assertEqual(BidConfirmation.objects.count(), 0)

        with patch(
            "apps.moderation.services.validation.classify_message",
            return_value=__import__(
                "apps.moderation.services.nova_classifier", fromlist=["Classification"]
            ).Classification("allow", "safe", 0.99),
        ):
            response = self.client.post(
                reverse("bidding:take"),
                {
                    "board_slug": "oklahoma",
                    "represented_entity": self.represented_entity.id,
                    "amount": "17.00",
                    "message": "TAKE THE BOARD.",
                    "age_acknowledged": "on",
                },
                HTTP_HX_REQUEST="true",
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Review your bid")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.age_acknowledgement_version, "18-plus-v1")
        self.assertIsNotNone(self.profile.age_acknowledged_at)

        response = self.client.get(reverse("schools:detail", kwargs={"slug": "oklahoma"}))
        self.assertNotContains(response, "I confirm that I am 18 or older")

    def test_purchase_evidence_preserves_age_acknowledgement(self) -> None:
        bid = Bid.objects.create(
            board=self.board,
            bidder=self.profile,
            represented_entity=self.represented_entity,
            message="TAKE THE BOARD.",
            amount_cents=1700,
            status=Bid.Status.WON,
            captured_at=timezone.now(),
        )
        published_at = timezone.now()
        evidence = record_purchase_evidence(
            bid=bid,
            published_at=published_at,
            guaranteed_until=published_at + timedelta(seconds=30),
        )

        self.assertEqual(
            evidence.age_acknowledgement_version,
            settings.TAKEBOARD_AGE_ACKNOWLEDGEMENT_VERSION,
        )
        self.assertEqual(evidence.age_acknowledged_at, self.profile.age_acknowledged_at)
        self.assertIsInstance(evidence, PurchaseEvidence)

    def test_only_bids_over_100_require_high_value_acknowledgement(self) -> None:
        self.profile.successful_bid_count = 10
        self.profile.created_at = timezone.now() - timedelta(days=8)
        self.profile.save(update_fields=["successful_bid_count", "created_at"])
        confirmation, decision = create_confirmation(
            board_id=self.board.id,
            profile_id=self.profile.id,
            represented_entity_id=self.represented_entity.id,
            amount_cents=10_100,
            message="TAKE THE BOARD.",
            validation=self.approved_validation(),
            rules=current_board_rules(),
            ip_address="127.0.0.1",
            user_agent="test-agent",
            request_id="test-high-value",
        )
        self.assertTrue(decision.requires_typed_confirmation)
        session = self.client.session
        session[AUTH_SESSION_KEY] = {
            "profile_id": self.profile.id,
            "cognito_sub": self.profile.cognito_sub,
            "expires_at": 4_000_000_000,
        }
        session.save()

        response = self.client.post(
            reverse("bidding:confirm", kwargs={"public_id": confirmation.public_id}),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "This bid is over $100.", status_code=400)
        self.assertContains(response, "Please acknowledge this high-value payment", status_code=400)
        response = self.client.post(
            reverse("bidding:confirm", kwargs={"public_id": confirmation.public_id}),
            {"terms_accepted": "on"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Type CONFIRM 101 to continue.", status_code=400)

    def test_bid_status_is_visible_only_to_the_authenticated_bidder(self) -> None:
        bid = Bid.objects.create(
            board=self.board,
            bidder=self.profile,
            represented_entity=self.represented_entity,
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
        self.assertEqual(response.json()["board_name"], "Oklahoma")
        self.assertEqual(response.json()["message"], "TAKE THE BOARD.")
        self.assertEqual(response.json()["represented_entity_name"], "Texas")
        self.assertEqual(response.json()["amount_cents"], 1700)

    def test_authorization_event_makes_the_bid_the_only_pending_challenger(self) -> None:
        bid = Bid.objects.create(
            board=self.board,
            bidder=self.profile,
            represented_entity=self.represented_entity,
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
            represented_entity=self.represented_entity,
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

    def test_dispute_webhook_suspends_paid_bidding_and_creates_a_chargeback_entry(self) -> None:
        bid = Bid.objects.create(
            board=self.board,
            bidder=self.profile,
            represented_entity=self.represented_entity,
            message="TAKE THE BOARD.",
            amount_cents=1700,
            status=Bid.Status.WON,
            stripe_payment_intent_id="pi_dispute_123",
            captured_at=timezone.now(),
        )
        PaymentCapture.objects.create(
            bid=bid,
            stripe_payment_intent_id="pi_dispute_123",
            gross_amount_cents=1700,
            currency="usd",
        )
        StripeEvent.objects.create(
            event_id="evt_dispute_123",
            event_type="charge.dispute.created",
            payload={"data": {"object": {"id": "dp_123", "payment_intent": "pi_dispute_123", "amount": 1700}}},
        )

        self.assertEqual(process_pending_stripe_events(), 1)
        bid.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(bid.status, Bid.Status.DISPUTED)
        self.assertEqual(bid.stripe_dispute_id, "dp_123")
        self.assertTrue(self.profile.paid_bidding_suspended)
        self.assertTrue(self.profile.has_open_dispute)
        self.assertEqual(self.profile.dispute_count, 1)
        self.assertTrue(LedgerEntry.objects.filter(type=LedgerEntry.Type.CHARGEBACK, bid=bid).exists())

    @patch("apps.payments.services.capture_payment.stripe.PaymentIntent.capture")
    def test_capture_records_immutable_stripe_fee_snapshot(self, capture) -> None:
        bid = Bid.objects.create(
            board=self.board,
            bidder=self.profile,
            represented_entity=self.represented_entity,
            message="TAKE THE BOARD.",
            amount_cents=1700,
            status=Bid.Status.AUTHORIZED,
            stripe_payment_intent_id="pi_capture_123",
            authorized_at=timezone.now(),
        )
        capture.return_value = {
            "id": "pi_capture_123",
            "status": "succeeded",
            "amount_received": 1700,
            "currency": "usd",
            "latest_charge": {
                "id": "ch_capture_123",
                "balance_transaction": {
                    "id": "txn_capture_123",
                    "amount": 1700,
                    "currency": "usd",
                    "fee": 79,
                    "net": 1621,
                    "fee_details": [{"amount": 79, "currency": "usd", "type": "stripe_fee"}],
                },
            },
        }

        self.assertTrue(capture_payment(bid))

        snapshot = PaymentCapture.objects.get(bid=bid)
        self.assertEqual(snapshot.stripe_payment_intent_id, "pi_capture_123")
        self.assertEqual(snapshot.stripe_charge_id, "ch_capture_123")
        self.assertEqual(snapshot.stripe_balance_transaction_id, "txn_capture_123")
        self.assertEqual(snapshot.gross_amount_cents, 1700)
        self.assertEqual(snapshot.stripe_fee_cents, 79)
        self.assertEqual(snapshot.net_amount_cents, 1621)
        self.assertEqual(snapshot.fee_status, PaymentCapture.FeeStatus.AVAILABLE)
        self.assertEqual(
            LedgerEntry.objects.filter(type=LedgerEntry.Type.BID_CAPTURE, bid=bid).count(),
            1,
        )
        self.assertEqual(capture.call_args.kwargs["expand"], ["latest_charge.balance_transaction"])

    @patch("apps.payments.services.capture_payment.stripe.PaymentIntent.capture")
    def test_charge_updated_completes_delayed_fee_snapshot(self, capture) -> None:
        bid = Bid.objects.create(
            board=self.board,
            bidder=self.profile,
            represented_entity=self.represented_entity,
            message="TAKE THE BOARD.",
            amount_cents=1700,
            status=Bid.Status.AUTHORIZED,
            stripe_payment_intent_id="pi_capture_delayed",
            authorized_at=timezone.now(),
        )
        capture.return_value = {
            "id": "pi_capture_delayed",
            "status": "succeeded",
            "amount_received": 1700,
            "currency": "usd",
            "latest_charge": {"id": "ch_capture_delayed", "balance_transaction": "txn_capture_delayed"},
        }
        self.assertTrue(capture_payment(bid))
        self.assertEqual(
            PaymentCapture.objects.get(bid=bid).fee_status,
            PaymentCapture.FeeStatus.PENDING,
        )
        StripeEvent.objects.create(
            event_id="evt_charge_updated",
            event_type="charge.updated",
            payload={
                "id": "evt_charge_updated",
                "type": "charge.updated",
                "data": {
                    "object": {
                        "id": "ch_capture_delayed",
                        "payment_intent": "pi_capture_delayed",
                        "balance_transaction": {
                            "id": "txn_capture_delayed",
                            "amount": 1700,
                            "currency": "usd",
                            "fee": 79,
                            "net": 1621,
                            "fee_details": [{"amount": 79, "currency": "usd", "type": "stripe_fee"}],
                        },
                    }
                },
            },
        )

        self.assertEqual(process_pending_stripe_events(), 1)

        snapshot = PaymentCapture.objects.get(bid=bid)
        self.assertEqual(snapshot.fee_status, PaymentCapture.FeeStatus.AVAILABLE)
        self.assertEqual(snapshot.stripe_fee_cents, 79)
        self.assertEqual(snapshot.net_amount_cents, 1621)
