"""Capture an authorized Stripe PaymentIntent."""

import logging

import stripe
from django.conf import settings

from apps.bidding.models import Bid


logger = logging.getLogger(__name__)


def capture_payment(bid: Bid) -> bool:
    if not settings.STRIPE_SECRET_KEY or not bid.stripe_payment_intent_id:
        return False

    try:
        payment_intent = stripe.PaymentIntent.capture(
            bid.stripe_payment_intent_id,
            api_key=settings.STRIPE_SECRET_KEY,
            idempotency_key=f"takeboard-capture-{bid.public_id}",
        )
    except stripe.error.StripeError:
        logger.warning("stripe_capture_failed", extra={"bid_id": bid.id})
        return False

    return payment_intent.get("status") == "succeeded"
