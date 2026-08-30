"""Read models for public standings and leaderboard views."""

from decimal import Decimal

from django.db.models import Case, CharField, Count, F, Max, Sum, Value, When

from apps.bidding.models import Bid
from apps.boards.models import BoardTakeover
from apps.schools.models import Competition
from apps.schools.services import default_competition

from .models import CompetitionPeriod
from .week_services import successful_takeovers_for_period


def _money(cents: int | None) -> str:
    return f"${Decimal(cents or 0) / 100:,.2f}"


def _rank(rows: list[dict]) -> list[dict]:
    for position, row in enumerate(rows, start=1):
        row["rank"] = position
        row["total_spend_display"] = _money(row.get("total_spend_cents"))
        row["biggest_bid_display"] = _money(row.get("biggest_bid_cents"))
    return rows


def _conference_label() -> Case:
    return Case(
        When(represented_entity__group_name="", then=Value("Independent")),
        default=F("represented_entity__group_name"),
        output_field=CharField(),
    )


def build_leaderboard(
    period: str = "all",
    *,
    competition: Competition | None = None,
) -> dict:
    """Build public rankings from successful, published takeovers only."""
    competition = competition or default_competition()
    active_week = CompetitionPeriod.objects.filter(
        competition=competition,
        active=True,
    ).order_by("-starts_at").first()
    effective_period = "week" if period == "week" and active_week else "all"

    takeovers = BoardTakeover.objects.filter(
        represented_entity__competition=competition,
        controller__is_banned=False,
        bid__status__in=[Bid.Status.WON, Bid.Status.DEMO_WON],
    ).exclude(report_case__status="removed")
    if effective_period == "week":
        takeovers = successful_takeovers_for_period(active_week)

    summary = takeovers.aggregate(
        total_spend_cents=Sum("amount_cents"),
        takeover_count=Count("id"),
        biggest_bid_cents=Max("amount_cents"),
    )
    summary["total_spend_cents"] = summary["total_spend_cents"] or 0
    summary["biggest_bid_cents"] = summary["biggest_bid_cents"] or 0

    fanbase_rows = list(
        takeovers.values(
            "represented_entity__name",
            "represented_entity__slug",
            "represented_entity__group_name",
        )
        .annotate(
            total_spend_cents=Sum("amount_cents"),
            takeovers=Count("id"),
            biggest_bid_cents=Max("amount_cents"),
        )
        .order_by("-total_spend_cents", "represented_entity__name")
    )
    for row in fanbase_rows:
        row["school_name"] = row.pop("represented_entity__name")
        row["school_slug"] = row.pop("represented_entity__slug")
        row["conference"] = row.pop("represented_entity__group_name") or "Independent"
    fanbase_rows = _rank(fanbase_rows)

    conference_rows = list(
        takeovers.annotate(conference_label=_conference_label())
        .values("conference_label")
        .annotate(
            total_spend_cents=Sum("amount_cents"),
            takeovers=Count("id"),
            schools=Count("represented_entity_id", distinct=True),
        )
        .order_by("-total_spend_cents", "conference_label")
    )
    for row in conference_rows:
        row["conference"] = row.pop("conference_label")
    conference_rows = _rank(conference_rows)

    spender_rows = list(
        takeovers.values("controller_id", "controller_display_name")
        .annotate(
            total_spend_cents=Sum("amount_cents"),
            takeovers=Count("id"),
            boards=Count("board_id", distinct=True),
            biggest_bid_cents=Max("amount_cents"),
        )
        .order_by("-total_spend_cents", "controller_display_name")
    )
    for row in spender_rows:
        row["display_name"] = row.pop("controller_display_name") or "Fan"
    spender_rows = _rank(spender_rows)

    attacked_rows = list(
        takeovers.values("board__entity__name", "board__entity__slug")
        .annotate(
            total_spend_cents=Sum("amount_cents"),
            takeovers=Count("id"),
        )
        .order_by("-takeovers", "-total_spend_cents", "board__entity__name")
    )
    for row in attacked_rows:
        row["school_name"] = row.pop("board__entity__name")
        row["school_slug"] = row.pop("board__entity__slug")
    attacked_rows = _rank(attacked_rows)

    biggest_moves = list(
        takeovers.select_related("board__entity", "represented_entity")
        .order_by("-amount_cents", "-occurred_at", "-id")[:5]
    )

    return {
        "period": effective_period,
        "active_week": active_week,
        "summary": {
            **summary,
            "total_spend_display": _money(summary["total_spend_cents"]),
            "biggest_bid_display": _money(summary["biggest_bid_cents"]),
            "conference_count": len(conference_rows),
            "school_count": len(fanbase_rows),
            "board_count": len(attacked_rows),
        },
        "fanbase_rows": fanbase_rows,
        "conference_rows": conference_rows,
        "spender_rows": spender_rows,
        "attacked_rows": attacked_rows,
        "biggest_moves": biggest_moves,
    }
