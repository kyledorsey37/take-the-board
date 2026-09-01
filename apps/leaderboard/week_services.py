"""Season-week boundaries, assignment, and cached weekly aggregates."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Count, F, Max, Q, Sum
from django.utils import timezone

from apps.bidding.models import Bid
from apps.boards.models import BoardTakeover
from apps.schools.models import Competition, Entity

from .models import EntityPeriodStats, CompetitionPeriod


RESET_WEEKDAY = 6  # Sunday; Python's weekday() uses Monday=0.
RESET_HOUR = 23
RESET_MINUTE = 59


@dataclass(frozen=True)
class CompetitionPeriodWindow:
    starts_at: datetime
    ends_at: datetime
    year: int
    week_number: int


@dataclass(frozen=True)
class WeeklyResetSchedule:
    """Public-facing reset timing derived from the server's current state."""

    server_now: datetime
    reset_at: datetime
    is_due: bool
    week_number: int


def current_period_window(now: datetime | None = None) -> CompetitionPeriodWindow:
    now = now or timezone.now()
    local_now = timezone.localtime(now, timezone.get_current_timezone())
    days_since_sunday = (local_now.weekday() - RESET_WEEKDAY) % 7
    starts_at = local_now.replace(
        hour=RESET_HOUR,
        minute=RESET_MINUTE,
        second=0,
        microsecond=0,
    ) - timedelta(days=days_since_sunday)
    if local_now < starts_at:
        starts_at -= timedelta(days=7)
    ends_at = starts_at + timedelta(days=7)
    iso_calendar = starts_at.date().isocalendar()
    return CompetitionPeriodWindow(
        starts_at=starts_at,
        ends_at=ends_at,
        year=iso_calendar.year,
        week_number=iso_calendar.week,
    )


def weekly_reset_schedule(
    *,
    competition: Competition,
    now: datetime | None = None,
) -> WeeklyResetSchedule:
    """Return the reset deadline without allowing a late job to fake a new week."""
    server_now = now or timezone.now()
    active_week = (
        CompetitionPeriod.objects.filter(competition=competition, active=True)
        .order_by("-starts_at")
        .first()
    )

    if active_week and active_week.ends_at <= server_now and not active_week.reset_completed_at:
        return WeeklyResetSchedule(
            server_now=server_now,
            reset_at=active_week.ends_at,
            is_due=True,
            week_number=active_week.week_number,
        )

    current_window = current_period_window(server_now)
    return WeeklyResetSchedule(
        server_now=server_now,
        reset_at=(
            active_week.ends_at
            if active_week and active_week.ends_at > server_now
            else current_window.ends_at
        ),
        is_due=False,
        week_number=(
            active_week.week_number
            if active_week and active_week.ends_at > server_now
            else current_window.week_number
        ),
    )


@transaction.atomic
def get_or_create_current_period(
    *,
    competition: Competition,
    now: datetime | None = None,
) -> CompetitionPeriod:
    active_week = CompetitionPeriod.objects.filter(
        competition=competition,
        active=True,
    ).order_by("-starts_at").first()
    if active_week:
        return active_week

    window = current_period_window(now)
    week, _ = CompetitionPeriod.objects.get_or_create(
        competition=competition,
        year=window.year,
        week_number=window.week_number,
        defaults={
            "starts_at": window.starts_at,
            "ends_at": window.ends_at,
            "active": True,
        },
    )
    if not week.active:
        week.active = True
        week.save(update_fields=["active"])
    return week


def successful_takeovers_for_period(period: CompetitionPeriod):
    return BoardTakeover.objects.filter(
        controller__is_banned=False,
        bid__status__in=[Bid.Status.WON, Bid.Status.DEMO_WON],
    ).exclude(report_case__status="removed").filter(
        Q(period=period)
        | Q(
            period__isnull=True,
            occurred_at__gte=period.starts_at,
            occurred_at__lt=period.ends_at,
        )
    )


@transaction.atomic
def rebuild_entity_period_stats(period: CompetitionPeriod) -> int:
    takeovers = successful_takeovers_for_period(period)
    aggregates = {
        row["represented_entity_id"]: row
        for row in takeovers.values("represented_entity_id").annotate(
            total_spend_cents=Sum("amount_cents"),
            takeovers=Count("id"),
            boards_attacked=Count(
                "id",
                filter=~Q(board__entity_id=F("represented_entity_id")),
            ),
            biggest_bid_cents=Max("amount_cents"),
        )
    }
    entities = list(Entity.objects.filter(competition=period.competition, active=True).order_by("pk"))
    EntityPeriodStats.objects.filter(period=period).delete()
    EntityPeriodStats.objects.bulk_create(
        [
            EntityPeriodStats(
                entity=entity,
                period=period,
                total_spend_cents=aggregates.get(entity.id, {}).get("total_spend_cents") or 0,
                takeovers=aggregates.get(entity.id, {}).get("takeovers") or 0,
                boards_attacked=aggregates.get(entity.id, {}).get("boards_attacked") or 0,
                biggest_bid_cents=aggregates.get(entity.id, {}).get("biggest_bid_cents") or 0,
            )
            for entity in entities
        ]
    )
    return len(entities)
