"""Capture an authorized Stripe PaymentIntent."""

import logging

import stripe
from django.conf import settings

from apps.bidding.models import Bid

from .capture_records import record_capture_from_payment_intent


logger = logging.getLogger(__name__)


def capture_payment(bid: Bid) -> bool:
    if not settings.STRIPE_SECRET_KEY or not bid.stripe_payment_intent_id:
        return False

    try:
        payment_intent = stripe.PaymentIntent.capture(
            bid.stripe_payment_intent_id,
            expand=["latest_charge.balance_transaction"],
            api_key=settings.STRIPE_SECRET_KEY,
            idempotency_key=f"takeboard-capture-{bid.public_id}",
        )
    except stripe.error.StripeError:
        logger.warning("stripe_capture_failed", extra={"bid_id": bid.id})
        return False

    if payment_intent.get("status") != "succeeded":
        return False

    try:
        # Provider success remains authoritative: an accounting write failure must
        # not label an already-captured card as a failed payment. The succeeding
        # PaymentIntent/charge webhooks provide a second, idempotent recording path.
        record_capture_from_payment_intent(bid=bid, payment_intent=payment_intent)
    except Exception:
        logger.exception("stripe_capture_recording_failed", extra={"bid_id": bid.id})
    return True
