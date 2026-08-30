"""Season-week boundaries, assignment, and cached weekly aggregates."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Count, F, Max, Q, Sum
from django.utils import timezone

from apps.bidding.models import Bid
from apps.boards.models import BoardTakeover
from apps.schools.models import School

from .models import SchoolWeekStats, SeasonWeek


RESET_WEEKDAY = 6  # Sunday; Python's weekday() uses Monday=0.
RESET_HOUR = 23
RESET_MINUTE = 59


@dataclass(frozen=True)
class SeasonWeekWindow:
    starts_at: datetime
    ends_at: datetime
    year: int
    week_number: int


def current_season_week_window(now: datetime | None = None) -> SeasonWeekWindow:
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
    return SeasonWeekWindow(
        starts_at=starts_at,
        ends_at=ends_at,
        year=iso_calendar.year,
        week_number=iso_calendar.week,
    )


@transaction.atomic
def get_or_create_current_season_week(now: datetime | None = None) -> SeasonWeek:
    active_week = SeasonWeek.objects.filter(active=True).order_by("-starts_at").first()
    if active_week:
        return active_week

    window = current_season_week_window(now)
    week, _ = SeasonWeek.objects.get_or_create(
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


def successful_takeovers_for_week(week: SeasonWeek):
    return BoardTakeover.objects.filter(
        controller__is_banned=False,
        bid__status__in=[Bid.Status.WON, Bid.Status.DEMO_WON],
    ).exclude(report_case__status="removed").filter(
        Q(season_week=week)
        | Q(
            season_week__isnull=True,
            occurred_at__gte=week.starts_at,
            occurred_at__lt=week.ends_at,
        )
    )


@transaction.atomic
def rebuild_school_week_stats(week: SeasonWeek) -> int:
    takeovers = successful_takeovers_for_week(week)
    aggregates = {
        row["represented_school_id"]: row
        for row in takeovers.values("represented_school_id").annotate(
            total_spend_cents=Sum("amount_cents"),
            takeovers=Count("id"),
            boards_attacked=Count(
                "id",
                filter=~Q(board__school_id=F("represented_school_id")),
            ),
            biggest_bid_cents=Max("amount_cents"),
        )
    }
    schools = list(School.objects.filter(active=True).order_by("pk"))
    SchoolWeekStats.objects.filter(week=week).delete()
    SchoolWeekStats.objects.bulk_create(
        [
            SchoolWeekStats(
                school=school,
                week=week,
                total_spend_cents=aggregates.get(school.id, {}).get("total_spend_cents") or 0,
                takeovers=aggregates.get(school.id, {}).get("takeovers") or 0,
                boards_attacked=aggregates.get(school.id, {}).get("boards_attacked") or 0,
                biggest_bid_cents=aggregates.get(school.id, {}).get("biggest_bid_cents") or 0,
            )
            for school in schools
        ]
    )
    return len(schools)
