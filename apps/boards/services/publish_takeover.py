"""Atomic publication of a bid that has already been captured."""

from datetime import datetime, timedelta

from apps.bidding.models import Bid
from apps.boards.models import Board, BoardTakeover


def publish_takeover(
    *,
    board: Board,
    bid: Bid,
    guaranteed_display_seconds: int,
    published_at: datetime,
) -> BoardTakeover:
    """Publish a captured bid while the caller holds the board row lock."""
    takeover = BoardTakeover.objects.create(
        board=board,
        bid=bid,
        previous_bid=board.current_bid,
        controller=bid.bidder,
        controller_display_name=bid.bidder.display_name,
        represented_entity=bid.represented_entity,
        period=bid.period,
        message=bid.message,
        amount_cents=bid.amount_cents,
    )
    board.current_bid = bid
    board.current_controller = bid.bidder
    board.current_amount_cents = bid.amount_cents
    board.current_message = bid.message
    board.pending_bid = None
    board.guaranteed_until = published_at + timedelta(seconds=guaranteed_display_seconds)
    board.version += 1
    board.save(
        update_fields=[
            "current_bid",
            "current_controller",
            "current_amount_cents",
            "current_message",
            "pending_bid",
            "guaranteed_until",
            "version",
            "updated_at",
        ]
    )
    return takeover
