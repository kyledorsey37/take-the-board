"""Apply stored Stripe events to local bid state from the worker."""

from datetime import datetime

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.bidding.models import Bid
from apps.bidding.services.finalize_bid import finalize_locked_pending_bid
from apps.bidding.services.rules import current_board_rules, minimum_takeover_cents
from apps.bidding.services.finalization_queue import enqueue_bid_finalization
from apps.boards.models import Board

from .cancel_authorization import cancel_authorization
from .capture_records import record_capture_from_payment_intent, update_capture_from_charge
from .capture_payment import capture_payment
from ..models import LedgerEntry, PaymentCapture, StripeEvent


AUTHORIZATION_EVENT = "payment_intent.amount_capturable_updated"

# A failed card attempt is not a failed bid.  Stripe can reuse the same
# PaymentIntent from an Embedded Checkout Session after the customer supplies a
# different payment method.  Keep these states retryable until Stripe either
# authorizes the PaymentIntent or cancels it.
RETRYABLE_PAYMENT_STATES = {
    Bid.Status.CREATED,
    Bid.Status.MODERATION_APPROVED,
    Bid.Status.CHECKOUT_CREATED,
}

# These states are already settled and must not be replaced by a cancellation
# event.  An authorized or processing bid remains cancellable until capture.
CANCELLATION_IMMUTABLE_STATES = {
    Bid.Status.WON,
    Bid.Status.DEMO_WON,
    Bid.Status.PAYMENT_FAILED,
    Bid.Status.AUTH_CANCELED,
    Bid.Status.OUTBID,
    Bid.Status.REFUNDED,
    Bid.Status.DISPUTED,
}


def _bid_public_id(event_object: dict) -> str:
    metadata = event_object.get("metadata") or {}
    return str(metadata.get("bid_id") or "")


def _find_bid(event_object: dict) -> Bid | None:
    public_id = _bid_public_id(event_object)
    if not public_id:
        return None
    return Bid.objects.filter(public_id=public_id).first()


def _handle_checkout_completed(event_object: dict) -> None:
    bid = _find_bid(event_object)
    if not bid:
        return

    updates = []
    payment_intent_id = event_object.get("payment_intent")
    if payment_intent_id and bid.stripe_payment_intent_id != payment_intent_id:
        bid.stripe_payment_intent_id = payment_intent_id
        updates.append("stripe_payment_intent_id")
    if updates:
        bid.save(update_fields=updates)


@transaction.atomic
def _authorize_bid(bid_id: int, payment_intent_id: str, now: datetime) -> list[Bid]:
    bid = Bid.objects.select_for_update().select_related("represented_entity").get(pk=bid_id)
    if bid.status not in {Bid.Status.CREATED, Bid.Status.CHECKOUT_CREATED}:
        return []

    board = Board.objects.select_for_update().get(pk=bid.board_id)
    rules = current_board_rules()
    if board.pending_bid_id and board.guaranteed_until and board.guaranteed_until <= now:
        finalize_locked_pending_bid(
            board=board,
            rules=rules,
            now=now,
            capture_pending_bid=capture_payment,
        )
        board.refresh_from_db(fields=["current_bid", "current_amount_cents", "pending_bid", "guaranteed_until"])

    pending_amount_cents = board.pending_bid.amount_cents if board.pending_bid_id else 0
    required_cents = minimum_takeover_cents(
        board.current_amount_cents,
        rules,
        pending_amount_cents,
    )
    bid.stripe_payment_intent_id = payment_intent_id
    if bid.amount_cents < required_cents:
        bid.status = Bid.Status.AUTH_CANCELED
        bid.canceled_at = now
        bid.save(update_fields=["stripe_payment_intent_id", "status", "canceled_at"])
        return [bid]

    canceled_bids = []
    if board.pending_bid_id and board.pending_bid_id != bid.id:
        previous = Bid.objects.select_for_update().get(pk=board.pending_bid_id)
        if previous.status == Bid.Status.AUTHORIZED:
            previous.status = Bid.Status.AUTH_CANCELED
            previous.canceled_at = now
            previous.save(update_fields=["status", "canceled_at"])
            canceled_bids.append(previous)

    bid.status = Bid.Status.AUTHORIZED
    bid.authorized_at = now
    bid.save(update_fields=["stripe_payment_intent_id", "status", "authorized_at"])
    board.pending_bid = bid
    board.save(update_fields=["pending_bid", "updated_at"])
    # Publishing is delayed until the protected window ends.  In SQS mode this
    # send is part of the same transaction: a provider failure rolls back the
    # authorization so the Stripe event can be retried safely.
    enqueue_bid_finalization(bid=bid, due_at=board.guaranteed_until, now=now)
    return canceled_bids


@transaction.atomic
def _handle_authorization(event_object: dict, now: datetime) -> None:
    bid = _find_bid(event_object)
    payment_intent_id = str(event_object.get("id") or "")
    if not bid or not payment_intent_id:
        return

    canceled_bids = _authorize_bid(bid.id, payment_intent_id, now)
    for canceled_bid in canceled_bids:
        cancel_authorization(canceled_bid)


@transaction.atomic
def _handle_payment_failed(event_object: dict, now: datetime) -> None:
    """Record the PaymentIntent while leaving a failed card attempt retryable."""
    bid = _find_bid(event_object)
    if not bid:
        return

    bid = Bid.objects.select_for_update().get(pk=bid.pk)
    if bid.status not in RETRYABLE_PAYMENT_STATES:
        return

    # PaymentIntent metadata normally supplies this earlier through Checkout or
    # the authorization event.  Saving the ID here also makes the retry path
    # observable without storing provider payload details in the bid.
    payment_intent_id = str(event_object.get("id") or "")
    updates = ["payment_failure_count", "payment_failed_at"]
    if payment_intent_id and not bid.stripe_payment_intent_id:
        bid.stripe_payment_intent_id = payment_intent_id
        updates.append("stripe_payment_intent_id")
    bid.payment_failure_count += 1
    bid.payment_failed_at = now
    bid.save(update_fields=updates)


@transaction.atomic
def _handle_payment_canceled(event_object: dict, now: datetime) -> None:
    """Invalidate a canceled PaymentIntent and release any local challenger."""
    bid = _find_bid(event_object)
    if not bid:
        return

    bid = Bid.objects.select_for_update().get(pk=bid.pk)
    if bid.status in CANCELLATION_IMMUTABLE_STATES:
        return

    updates = ["status", "canceled_at"]
    payment_intent_id = str(event_object.get("id") or "")
    if payment_intent_id and not bid.stripe_payment_intent_id:
        bid.stripe_payment_intent_id = payment_intent_id
        updates.append("stripe_payment_intent_id")
    bid.status = Bid.Status.AUTH_CANCELED
    bid.canceled_at = now
    bid.save(update_fields=updates)

    board = Board.objects.select_for_update().get(pk=bid.board_id)
    if board.pending_bid_id == bid.id:
        board.pending_bid = None
        board.save(update_fields=["pending_bid", "updated_at"])


def _handle_payment_succeeded(event_object: dict) -> None:
    bid = _find_bid(event_object)
    if not bid:
        return
    # This is deliberately idempotent and also repairs a rare local write failure
    # after Stripe has successfully captured the payment.
    record_capture_from_payment_intent(bid=bid, payment_intent=event_object)


def _handle_charge_updated(event_object: dict) -> None:
    # The charge event is sent when Stripe has asynchronously attached the balance
    # transaction. Its fee data completes the immutable capture snapshot.
    update_capture_from_charge(charge=event_object)


@transaction.atomic
def _handle_dispute_created(event_object: dict, now: datetime) -> None:
    """Immediately suspend paid bidding and preserve a ledger audit trail."""
    dispute_id = str(event_object.get("id") or "")
    payment_intent_id = str(event_object.get("payment_intent") or "")
    charge_id = str(event_object.get("charge") or "")
    capture = PaymentCapture.objects.select_related("bid").filter(
        stripe_payment_intent_id=payment_intent_id
    ).first()
    if not capture and charge_id:
        capture = PaymentCapture.objects.select_related("bid").filter(stripe_charge_id=charge_id).first()
    if not capture or not dispute_id:
        return
    bid = Bid.objects.select_for_update().select_related("bidder", "represented_entity").get(pk=capture.bid_id)
    if bid.stripe_dispute_id == dispute_id:
        return
    bid.status = Bid.Status.DISPUTED
    bid.stripe_dispute_id = dispute_id
    bid.save(update_fields=["status", "stripe_dispute_id"])
    bidder = bid.bidder
    bidder.__class__.objects.filter(pk=bidder.id).update(
        dispute_count=F("dispute_count") + 1,
        has_open_dispute=True,
        paid_bidding_suspended=True,
        last_dispute_at=now,
        risk_tier="suspended",
    )
    amount = int(event_object.get("amount") or bid.amount_cents)
    LedgerEntry.objects.get_or_create(
        type=LedgerEntry.Type.CHARGEBACK,
        bid=bid,
        defaults={"amount_cents": -amount, "user": bidder, "entity": bid.represented_entity},
    )


@transaction.atomic
def process_stripe_event(event_id: str) -> bool:
    event = StripeEvent.objects.select_for_update().get(event_id=event_id)
    if event.processed_at:
        return False

    event_object = event.payload.get("data", {}).get("object", {})
    now = timezone.now()
    if event.event_type == "checkout.session.completed":
        _handle_checkout_completed(event_object)
    elif event.event_type == AUTHORIZATION_EVENT:
        _handle_authorization(event_object, now)
    elif event.event_type == "payment_intent.payment_failed":
        _handle_payment_failed(event_object, now)
    elif event.event_type == "payment_intent.canceled":
        _handle_payment_canceled(event_object, now)
    elif event.event_type == "payment_intent.succeeded":
        _handle_payment_succeeded(event_object)
    elif event.event_type == "charge.updated":
        _handle_charge_updated(event_object)
    elif event.event_type == "charge.dispute.created":
        _handle_dispute_created(event_object, now)

    event.processed_at = now
    event.save(update_fields=["processed_at"])
    return True


def process_pending_stripe_events(limit: int = 100) -> int:
    event_ids = list(
        StripeEvent.objects.filter(processed_at__isnull=True)
        .order_by("received_at", "id")
        .values_list("event_id", flat=True)[:limit]
    )
    return sum(process_stripe_event(event_id) for event_id in event_ids)
