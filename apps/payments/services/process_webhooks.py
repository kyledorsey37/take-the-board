"""Apply stored Stripe events to local bid state from the worker."""

from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.bidding.models import Bid
from apps.bidding.services.finalize_bid import finalize_locked_pending_bid
from apps.bidding.services.rules import current_board_rules, minimum_takeover_cents
from apps.boards.models import Board

from .cancel_authorization import cancel_authorization
from .capture_payment import capture_payment
from ..models import StripeEvent


AUTHORIZATION_EVENT = "payment_intent.amount_capturable_updated"


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
    bid = Bid.objects.select_for_update().select_related("represented_school").get(pk=bid_id)
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
def _handle_payment_failure(event_object: dict, status: str, now: datetime) -> None:
    bid = _find_bid(event_object)
    if not bid:
        return

    bid = Bid.objects.select_for_update().get(pk=bid.pk)
    if bid.status in {Bid.Status.WON, Bid.Status.DEMO_WON, Bid.Status.REFUNDED}:
        return
    bid.status = status
    if status == Bid.Status.AUTH_CANCELED:
        bid.canceled_at = now
    bid.save(update_fields=["status", "canceled_at"] if status == Bid.Status.AUTH_CANCELED else ["status"])

    board = Board.objects.select_for_update().get(pk=bid.board_id)
    if board.pending_bid_id == bid.id:
        board.pending_bid = None
        board.save(update_fields=["pending_bid", "updated_at"])


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
        _handle_payment_failure(event_object, Bid.Status.PAYMENT_FAILED, now)
    elif event.event_type == "payment_intent.canceled":
        _handle_payment_failure(event_object, Bid.Status.AUTH_CANCELED, now)

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
