"""Weekly board rollover and historical weekly-stat maintenance."""

from dataclasses import dataclass
from datetime import datetime
from collections.abc import Callable

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.bidding.models import Bid
from apps.leaderboard.models import CompetitionPeriod
from apps.leaderboard.week_services import (
    current_period_window,
    rebuild_entity_period_stats,
)
from apps.schools.models import Competition

from ..models import Board


CancelPendingAuthorization = Callable[[Bid], bool]


class WeeklyResetError(Exception):
    """Raised when a pending payment authorization cannot be released."""


@dataclass(frozen=True)
class WeeklyResetResult:
    period: CompetitionPeriod
    boards_reset: int
    stats_rows: int
    already_reset: bool


@transaction.atomic
def reset_boards(
    *,
    competition: Competition,
    now: datetime | None = None,
    cancel_pending_authorization: CancelPendingAuthorization | None = None,
) -> WeeklyResetResult:
    """Reset live boards once for the current Sunday-to-Sunday season week."""
    now = now or timezone.now()
    window = current_period_window(now)
    period, _ = CompetitionPeriod.objects.get_or_create(
        competition=competition,
        year=window.year,
        week_number=window.week_number,
        defaults={
            "starts_at": window.starts_at,
            "ends_at": window.ends_at,
        },
    )

    if period.reset_completed_at:
        return WeeklyResetResult(
            period=period,
            boards_reset=0,
            stats_rows=0,
            already_reset=True,
        )

    previous_week = (
        CompetitionPeriod.objects.filter(competition=competition, ends_at__lte=period.starts_at)
        .exclude(pk=period.pk)
        .order_by("-ends_at")
        .first()
    )
    if previous_week:
        rebuild_entity_period_stats(previous_week)

    CompetitionPeriod.objects.filter(competition=competition, active=True).exclude(pk=period.pk).update(active=False)
    period.active = True
    period.reset_completed_at = now
    period.save(update_fields=["active", "reset_completed_at"])

    boards = list(Board.objects.select_for_update().filter(entity__competition=competition).order_by("pk"))
    for board in boards:
        if board.pending_bid_id:
            pending_bid = Bid.objects.select_for_update().get(pk=board.pending_bid_id)
            if pending_bid.status == Bid.Status.AUTHORIZED and cancel_pending_authorization:
                if not cancel_pending_authorization(pending_bid):
                    raise WeeklyResetError(
                        f"Could not release pending authorization for bid {pending_bid.id}."
                    )
            if pending_bid.status in {
                Bid.Status.CREATED,
                Bid.Status.CHECKOUT_CREATED,
                Bid.Status.AUTHORIZED,
            }:
                pending_bid.status = Bid.Status.AUTH_CANCELED
                pending_bid.canceled_at = now
                pending_bid.save(update_fields=["status", "canceled_at"])

        board.current_bid = None
        board.current_controller = None
        board.current_amount_cents = 0
        board.current_message = settings.TAKEBOARD_DEFAULT_BOARD_MESSAGE
        board.pending_bid = None
        board.guaranteed_until = None
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

    stats_rows = rebuild_entity_period_stats(period)
    return WeeklyResetResult(
        period=period,
        boards_reset=len(boards),
        stats_rows=stats_rows,
        already_reset=False,
    )
