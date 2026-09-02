"""Finalize a due pending challenger after the current guarantee expires."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.bidding.models import Bid
from apps.boards.models import Board
from apps.boards.services.publish_takeover import publish_takeover
from apps.core.models import Activity

from .rules import BoardRules


@dataclass(frozen=True)
class FinalizationResult:
    board_id: int
    bid_id: int | None
    published: bool


CapturePendingBid = Callable[[Bid], bool]


def finalize_locked_pending_bid(
    *,
    board: Board,
    rules: BoardRules,
    now: datetime,
    capture_pending_bid: CapturePendingBid | None = None,
) -> FinalizationResult | None:
    """Finalize a pending bid while the caller holds a lock on ``board``."""
    if not board.pending_bid_id:
        return None
    if board.guaranteed_until and board.guaranteed_until > now:
        return None

    pending_bid = Bid.objects.select_related("bidder", "represented_entity").get(pk=board.pending_bid_id)
    if pending_bid.status != Bid.Status.AUTHORIZED:
        board.pending_bid = None
        board.save(update_fields=["pending_bid", "updated_at"])
        return FinalizationResult(board_id=board.id, bid_id=pending_bid.id, published=False)

    if capture_pending_bid is not None and not capture_pending_bid(pending_bid):
        pending_bid.status = Bid.Status.PAYMENT_FAILED
        pending_bid.payment_failure_count += 1
        pending_bid.payment_failed_at = now
        pending_bid.save(update_fields=["status", "payment_failure_count", "payment_failed_at"])
        board.pending_bid = None
        board.save(update_fields=["pending_bid", "updated_at"])
        Activity.objects.create(
            type="demo_pending_capture_failed",
            user=pending_bid.bidder,
            board=board,
            metadata={"bid_id": pending_bid.id, "amount_cents": pending_bid.amount_cents},
        )
        return FinalizationResult(board_id=board.id, bid_id=pending_bid.id, published=False)

    pending_bid.status = Bid.Status.WON if capture_pending_bid is not None else Bid.Status.DEMO_WON
    pending_bid.captured_at = now
    pending_bid.save(update_fields=["status", "captured_at"])
    publish_takeover(
        board=board,
        bid=pending_bid,
        guaranteed_display_seconds=rules.guaranteed_display_seconds,
        published_at=now,
    )
    if capture_pending_bid is not None:
        # Import locally to keep free-play bidding independent of payments at import time.
        from apps.payments.services.evidence import record_purchase_evidence

        board.refresh_from_db(fields=["guaranteed_until"])
        record_purchase_evidence(
            bid=pending_bid,
            published_at=now,
            guaranteed_until=board.guaranteed_until,
        )
    Activity.objects.create(
        type=(
            "pending_takeover_published"
            if capture_pending_bid is not None
            else "demo_pending_challenge_published"
        ),
        user=pending_bid.bidder,
        board=board,
        metadata={"bid_id": pending_bid.id, "amount_cents": pending_bid.amount_cents},
    )
    return FinalizationResult(board_id=board.id, bid_id=pending_bid.id, published=True)


@transaction.atomic
def finalize_due_board(
    *,
    board_id: int,
    rules: BoardRules,
    now: datetime | None = None,
    capture_pending_bid: CapturePendingBid | None = None,
    expected_pending_bid_id: int | None = None,
) -> FinalizationResult | None:
    now = now or timezone.now()
    board = Board.objects.select_for_update().get(pk=board_id)
    if expected_pending_bid_id is not None and board.pending_bid_id != expected_pending_bid_id:
        return None
    return finalize_locked_pending_bid(
        board=board,
        rules=rules,
        now=now,
        capture_pending_bid=capture_pending_bid,
    )


def finalize_due_boards(
    *,
    rules: BoardRules,
    now: datetime | None = None,
    capture_pending_bid: CapturePendingBid | None = None,
    limit: int = 100,
) -> list[FinalizationResult]:
    now = now or timezone.now()
    due_board_ids = list(
        Board.objects.filter(pending_bid__isnull=False)
        .filter(Q(guaranteed_until__lte=now) | Q(guaranteed_until__isnull=True))
        .order_by("guaranteed_until", "id")
        .values_list("id", flat=True)[:limit]
    )
    return [
        result
        for board_id in due_board_ids
        if (
            result := finalize_due_board(
                board_id=board_id,
                rules=rules,
                now=now,
                capture_pending_bid=capture_pending_bid,
            )
        )
        is not None
    ]
