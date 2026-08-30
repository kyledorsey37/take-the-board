"""Persist and reconcile Stripe accounting snapshots for successful captures."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import stripe
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.bidding.models import Bid

from ..models import LedgerEntry, PaymentCapture


logger = logging.getLogger(__name__)
FEE_RECONCILIATION_INTERVAL = timedelta(seconds=30)


def _value(stripe_object: Any, key: str, default: Any = None) -> Any:
    if isinstance(stripe_object, dict):
        return stripe_object.get(key, default)
    return getattr(stripe_object, key, default)


def _object_id(stripe_object: Any) -> str:
    if isinstance(stripe_object, str):
        return stripe_object
    return str(_value(stripe_object, "id", "") or "")


def _fee_details(balance_transaction: Any) -> list[dict[str, Any]]:
    """Keep only accounting-safe fee values, never a raw Stripe provider payload."""
    details = _value(balance_transaction, "fee_details", []) or []
    return [
        {
            "amount": int(_value(detail, "amount", 0) or 0),
            "currency": str(_value(detail, "currency", "") or "").lower(),
            "type": str(_value(detail, "type", "") or ""),
        }
        for detail in details
    ]


def _apply_charge_details(capture: PaymentCapture, charge: Any) -> bool:
    """Fill previously unknown provider identifiers and fee data exactly once."""
    update_fields: list[str] = []
    charge_id = _object_id(charge)
    if charge_id and not capture.stripe_charge_id:
        capture.stripe_charge_id = charge_id
        update_fields.append("stripe_charge_id")

    balance_transaction = _value(charge, "balance_transaction")
    if not balance_transaction:
        if update_fields:
            capture.save(update_fields=update_fields)
        return False

    balance_transaction_id = _object_id(balance_transaction)
    if balance_transaction_id and not capture.stripe_balance_transaction_id:
        capture.stripe_balance_transaction_id = balance_transaction_id
        update_fields.append("stripe_balance_transaction_id")

    fee = _value(balance_transaction, "fee")
    net = _value(balance_transaction, "net")
    if fee is None or net is None or capture.fee_status == PaymentCapture.FeeStatus.AVAILABLE:
        if update_fields:
            capture.save(update_fields=update_fields)
        return False

    gross = _value(balance_transaction, "amount")
    if gross is not None and int(gross) != capture.gross_amount_cents:
        logger.error(
            "stripe_capture_amount_mismatch",
            extra={"capture_id": capture.id, "bid_id": capture.bid_id},
        )
        if update_fields:
            capture.save(update_fields=update_fields)
        return False

    currency = str(_value(balance_transaction, "currency", "") or "").lower()
    if currency and currency != capture.currency:
        logger.error(
            "stripe_capture_currency_mismatch",
            extra={"capture_id": capture.id, "bid_id": capture.bid_id},
        )
        if update_fields:
            capture.save(update_fields=update_fields)
        return False

    capture.stripe_fee_cents = int(fee)
    capture.net_amount_cents = int(net)
    capture.fee_details = _fee_details(balance_transaction)
    capture.fee_status = PaymentCapture.FeeStatus.AVAILABLE
    capture.fee_available_at = timezone.now()
    update_fields.extend(
        ["stripe_fee_cents", "net_amount_cents", "fee_details", "fee_status", "fee_available_at"]
    )
    capture.save(update_fields=update_fields)
    return True


@transaction.atomic
def record_capture_from_payment_intent(*, bid: Bid, payment_intent: Any) -> PaymentCapture | None:
    """Create the gross capture record and apply fee data if Stripe already has it."""
    payment_intent_id = _object_id(payment_intent)
    if not payment_intent_id or _value(payment_intent, "status") != "succeeded":
        return None
    if bid.stripe_payment_intent_id and payment_intent_id != bid.stripe_payment_intent_id:
        logger.error("stripe_capture_payment_intent_mismatch", extra={"bid_id": bid.id})
        return None

    gross_amount_cents = int(
        _value(payment_intent, "amount_received", _value(payment_intent, "amount", bid.amount_cents))
        or bid.amount_cents
    )
    currency = str(_value(payment_intent, "currency", "usd") or "usd").lower()
    if gross_amount_cents != bid.amount_cents:
        logger.error("stripe_capture_amount_mismatch", extra={"bid_id": bid.id})
        return None

    capture, created = PaymentCapture.objects.get_or_create(
        bid=bid,
        defaults={
            "stripe_payment_intent_id": payment_intent_id,
            "gross_amount_cents": gross_amount_cents,
            "currency": currency,
        },
    )
    if not created and capture.stripe_payment_intent_id != payment_intent_id:
        logger.error("stripe_capture_duplicate_bid_mismatch", extra={"bid_id": bid.id})
        return None

    if created:
        LedgerEntry.objects.get_or_create(
            type=LedgerEntry.Type.BID_CAPTURE,
            bid=bid,
            defaults={
                "amount_cents": gross_amount_cents,
                "user": bid.bidder,
                "school": bid.represented_school,
            },
        )
    _apply_charge_details(capture, _value(payment_intent, "latest_charge"))
    return capture


@transaction.atomic
def update_capture_from_charge(*, charge: Any) -> bool:
    """Use a charge webhook to attach any immediately available fee fields."""
    payment_intent_id = _object_id(_value(charge, "payment_intent"))
    if not payment_intent_id:
        return False
    try:
        capture = PaymentCapture.objects.select_for_update().get(
            stripe_payment_intent_id=payment_intent_id
        )
    except PaymentCapture.DoesNotExist:
        return False
    return _apply_charge_details(capture, charge)


def reconcile_pending_capture_fees(limit: int = 100) -> int:
    """Retry delayed Stripe balance-transaction lookups without retaining DB locks."""
    if not settings.STRIPE_SECRET_KEY:
        return 0
    retry_before = timezone.now() - FEE_RECONCILIATION_INTERVAL
    capture_ids = list(
        PaymentCapture.objects.filter(fee_status=PaymentCapture.FeeStatus.PENDING)
        .filter(Q(fee_reconciliation_attempted_at__isnull=True) | Q(fee_reconciliation_attempted_at__lte=retry_before))
        .order_by("captured_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    reconciled = 0
    for capture_id in capture_ids:
        capture = PaymentCapture.objects.filter(pk=capture_id).first()
        if not capture:
            continue
        try:
            payment_intent = stripe.PaymentIntent.retrieve(
                capture.stripe_payment_intent_id,
                expand=["latest_charge.balance_transaction"],
                api_key=settings.STRIPE_SECRET_KEY,
            )
        except stripe.error.StripeError:
            logger.warning("stripe_capture_fee_reconciliation_failed", extra={"capture_id": capture.id})
            payment_intent = None

        with transaction.atomic():
            capture = PaymentCapture.objects.select_for_update().get(pk=capture_id)
            if capture.fee_status != PaymentCapture.FeeStatus.PENDING:
                continue
            capture.fee_reconciliation_attempted_at = timezone.now()
            capture.fee_reconciliation_attempts += 1
            capture.save(
                update_fields=["fee_reconciliation_attempted_at", "fee_reconciliation_attempts"]
            )
            if payment_intent and _value(payment_intent, "status") == "succeeded":
                reconciled += int(_apply_charge_details(capture, _value(payment_intent, "latest_charge")))
    return reconciled


def backfill_missing_capture_records(limit: int = 100) -> int:
    """Create snapshots for historical Stripe captures made before this feature."""
    if not settings.STRIPE_SECRET_KEY:
        return 0
    bid_ids = list(
        Bid.objects.filter(
            status__in=[Bid.Status.WON, Bid.Status.REFUNDED, Bid.Status.DISPUTED],
            stripe_payment_intent_id__gt="",
            payment_capture__isnull=True,
        )
        .order_by("captured_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    recorded = 0
    for bid_id in bid_ids:
        bid = Bid.objects.select_related("bidder", "represented_school").get(pk=bid_id)
        try:
            payment_intent = stripe.PaymentIntent.retrieve(
                bid.stripe_payment_intent_id,
                expand=["latest_charge.balance_transaction"],
                api_key=settings.STRIPE_SECRET_KEY,
            )
        except stripe.error.StripeError:
            logger.warning("stripe_capture_backfill_failed", extra={"bid_id": bid.id})
            continue
        if record_capture_from_payment_intent(bid=bid, payment_intent=payment_intent):
            recorded += 1
    return recorded
