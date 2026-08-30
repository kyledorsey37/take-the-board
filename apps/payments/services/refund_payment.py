"""Stripe refund service boundary."""

from __future__ import annotations

import logging

import stripe
from django.conf import settings

from apps.bidding.models import Bid


logger = logging.getLogger(__name__)


def refund_payment(*, bid: Bid, amount_cents: int, idempotency_key: str) -> str | None:
    """Refund an exact, server-calculated amount and return the opaque refund ID."""
    if not settings.STRIPE_SECRET_KEY or not bid.stripe_payment_intent_id or amount_cents <= 0:
        return None
    try:
        refund = stripe.Refund.create(
            payment_intent=bid.stripe_payment_intent_id,
            amount=amount_cents,
            api_key=settings.STRIPE_SECRET_KEY,
            idempotency_key=idempotency_key,
        )
    except stripe.error.StripeError as error:
        logger.warning(
            "stripe_refund_failed",
            extra={"bid_id": bid.id, "stripe_error_code": getattr(error, "code", "stripe_error")},
        )
        return None
    if refund.get("status") != "succeeded":
        return None
    return str(refund.get("id") or "")
