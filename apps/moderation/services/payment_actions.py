"""Retryable out-of-transaction processor for moderation payment actions."""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.bidding.models import Bid
from apps.core.sentry import capture_critical_message
from apps.moderation.models import ModerationPaymentAction
from apps.payments.models import LedgerEntry, PaymentCapture
from apps.payments.services.cancel_authorization import cancel_authorization
from apps.payments.services.refund_payment import refund_payment


logger = logging.getLogger(__name__)


def _idempotency_key(action: ModerationPaymentAction) -> str:
    return f"takeboard-moderation-{action.operation}-{action.case.public_id}"


def _refund_amount_after_processing_fee(bid: Bid) -> int | None:
    """Return the documented net refund only after Stripe's actual fee is known."""
    try:
        capture = bid.payment_capture
    except Bid.payment_capture.RelatedObjectDoesNotExist:
        return None
    if (
        capture.fee_status != PaymentCapture.FeeStatus.AVAILABLE
        or capture.stripe_fee_cents is None
        or capture.net_amount_cents is None
    ):
        return None
    if capture.gross_amount_cents != bid.amount_cents:
        logger.error("moderation_refund_capture_amount_mismatch", extra={"bid_id": bid.id})
        capture_critical_message("payment_refund_integrity_mismatch")
        return None
    if capture.net_amount_cents != capture.gross_amount_cents - capture.stripe_fee_cents:
        logger.error("moderation_refund_capture_net_mismatch", extra={"bid_id": bid.id})
        capture_critical_message("payment_refund_integrity_mismatch")
        return None
    return capture.net_amount_cents


def process_payment_action(action_id: int) -> bool:
    """Perform one provider operation without retaining a DB lock during I/O."""
    with transaction.atomic():
        action = (
            ModerationPaymentAction.objects.select_for_update()
            .select_related("case", "bid", "bid__bidder", "bid__board__entity")
            .get(pk=action_id)
        )
        if action.status in {
            ModerationPaymentAction.Status.SUCCEEDED,
            ModerationPaymentAction.Status.NOT_REQUIRED,
            ModerationPaymentAction.Status.PROCESSING,
        }:
            return action.status == ModerationPaymentAction.Status.SUCCEEDED
        action.status = ModerationPaymentAction.Status.PROCESSING
        operation = action.operation
        bid = action.bid
        if operation == ModerationPaymentAction.Operation.REFUND:
            amount_cents = _refund_amount_after_processing_fee(bid)
            if amount_cents is None:
                action.amount_cents = None
                action.last_error_code = "stripe_fee_data_pending"
                action.save(update_fields=["amount_cents", "last_error_code", "updated_at"])
                return False
            if amount_cents <= 0:
                action.status = ModerationPaymentAction.Status.NOT_REQUIRED
                action.amount_cents = 0
                action.last_error_code = "refund_amount_zero"
                action.completed_at = timezone.now()
                action.save(
                    update_fields=["status", "amount_cents", "last_error_code", "completed_at", "updated_at"]
                )
                return False
            action.amount_cents = amount_cents
        action.attempts += 1
        action.last_error_code = ""
        action.save(update_fields=["status", "amount_cents", "attempts", "last_error_code", "updated_at"])
        key = _idempotency_key(action)

    provider_reference = ""
    try:
        if operation == ModerationPaymentAction.Operation.CANCEL_AUTHORIZATION:
            succeeded = cancel_authorization(bid, idempotency_key=key)
            provider_reference = bid.stripe_payment_intent_id if succeeded else ""
        else:
            provider_reference = refund_payment(
                bid=bid,
                amount_cents=action.amount_cents,
                idempotency_key=key,
            ) or ""
            succeeded = bool(provider_reference)
    except Exception:
        # Deliberately do not log provider text/payloads.
        succeeded = False

    with transaction.atomic():
        action = ModerationPaymentAction.objects.select_for_update().select_related("bid").get(pk=action_id)
        if action.status != ModerationPaymentAction.Status.PROCESSING:
            return action.status == ModerationPaymentAction.Status.SUCCEEDED
        if not succeeded:
            action.status = ModerationPaymentAction.Status.FAILED
            action.last_error_code = "provider_operation_failed"
            action.save(update_fields=["status", "last_error_code", "updated_at"])
            logger.warning("message_report_payment_action_failed", extra={"action_id": str(action.public_id)})
            return False

        action.status = ModerationPaymentAction.Status.SUCCEEDED
        action.provider_reference = provider_reference
        action.completed_at = timezone.now()
        action.save(update_fields=["status", "provider_reference", "completed_at", "updated_at"])
        if action.operation == ModerationPaymentAction.Operation.REFUND:
            bid = action.bid
            bid.status = Bid.Status.REFUNDED
            bid.save(update_fields=["status"])
            LedgerEntry.objects.get_or_create(
                type=LedgerEntry.Type.REFUND,
                bid=bid,
                defaults={
                    "amount_cents": -action.amount_cents,
                    "user": bid.bidder,
                    "entity": bid.represented_entity,
                },
            )
            bid.bidder.__class__.objects.filter(pk=bid.bidder_id).update(
                refund_count=F("refund_count") + 1,
            )
        logger.info("message_report_payment_action_succeeded", extra={"action_id": str(action.public_id)})
        return True


def process_pending_payment_actions(limit: int = 100) -> int:
    action_ids = list(
        ModerationPaymentAction.objects.filter(
            status__in=[ModerationPaymentAction.Status.PENDING, ModerationPaymentAction.Status.FAILED]
        )
        .order_by("created_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    return sum(process_payment_action(action_id) for action_id in action_ids)
