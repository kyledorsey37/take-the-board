"""Read models for rivalry scoreboards."""

from decimal import Decimal
import re

from django.db.models import Count, Max, Q, Sum

from apps.bidding.models import Bid
from apps.boards.models import Board, BoardTakeover
from apps.leaderboard.models import SeasonWeek

from .models import Rivalry


def _money(cents: int | None) -> str:
    return f"${Decimal(cents or 0) / 100:,.2f}"


HEX_COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")


def _successful_takeovers(rivalry: Rivalry, period: str):
    school_ids = [rivalry.school_a_id, rivalry.school_b_id]
    takeovers = BoardTakeover.objects.filter(
        controller__is_banned=False,
        bid__status__in=[Bid.Status.WON, Bid.Status.DEMO_WON],
        represented_school_id__in=school_ids,
    ).filter(Q(board__school_id=school_ids[0]) | Q(board__school_id=school_ids[1]))

    active_week = SeasonWeek.objects.filter(active=True).order_by("-starts_at").first()
    if period == "week" and active_week:
        takeovers = takeovers.filter(
            occurred_at__gte=active_week.starts_at,
            occurred_at__lt=active_week.ends_at,
        )
    return takeovers, active_week


def _side_stats(takeovers, school, other_school) -> dict:
    stats = takeovers.filter(represented_school_id=school.id).aggregate(
        takeovers=Count("id"),
        spend_cents=Sum("amount_cents"),
        biggest_move_cents=Max("amount_cents"),
    )
    stats["spend_cents"] = stats["spend_cents"] or 0
    stats["biggest_move_cents"] = stats["biggest_move_cents"] or 0
    stats["school"] = school
    stats["accent_color"] = (
        school.accent_color
        if HEX_COLOR_PATTERN.fullmatch(school.accent_color)
        else "#b3262f"
    )
    stats["spend_display"] = _money(stats["spend_cents"])
    stats["biggest_move_display"] = _money(stats["biggest_move_cents"])
    stats["attacks"] = takeovers.filter(
        represented_school_id=school.id,
        board__school_id=other_school.id,
    ).count()
    return stats


def build_rivalry_scoreboard(rivalry: Rivalry, period: str = "all") -> dict:
    takeovers, active_week = _successful_takeovers(rivalry, period)
    effective_period = "week" if period == "week" and active_week else "all"
    school_a = rivalry.school_a
    school_b = rivalry.school_b
    side_a = _side_stats(takeovers, school_a, school_b)
    side_b = _side_stats(takeovers, school_b, school_a)

    if side_a["takeovers"] > side_b["takeovers"]:
        leader = side_a
        lead_text = f"{school_a.name} leads by {side_a['takeovers'] - side_b['takeovers']} takeover wins."
    elif side_b["takeovers"] > side_a["takeovers"]:
        leader = side_b
        lead_text = f"{school_b.name} leads by {side_b['takeovers'] - side_a['takeovers']} takeover wins."
    elif side_a["spend_cents"] > side_b["spend_cents"]:
        leader = side_a
        lead_text = f"{school_a.name} leads on backing after a tie in takeover wins."
    elif side_b["spend_cents"] > side_a["spend_cents"]:
        leader = side_b
        lead_text = f"{school_b.name} leads on backing after a tie in takeover wins."
    else:
        leader = None
        lead_text = "Dead even."

    boards = list(
        Board.objects.filter(school_id__in=[school_a.id, school_b.id])
        .select_related("school", "current_controller", "current_bid__represented_school")
        .order_by("school__name")
    )
    for board in boards:
        board.safe_accent_color = (
            board.school.accent_color
            if HEX_COLOR_PATTERN.fullmatch(board.school.accent_color)
            else "#b3262f"
        )
    recent_moves = list(
        takeovers.select_related("board__school", "represented_school")
        .order_by("-occurred_at", "-id")[:6]
    )
    biggest_move = takeovers.select_related("board__school", "represented_school").order_by(
        "-amount_cents", "-occurred_at", "-id"
    ).first()

    leader_school_id = leader["school"].id if leader else None

    return {
        "rivalry": rivalry,
        "period": effective_period,
        "active_week": active_week,
        "school_a": side_a,
        "school_b": side_b,
        "sides": [side_a, side_b],
        "leader": leader,
        "leader_school_id": leader_school_id,
        "lead_text": lead_text,
        "boards": boards,
        "recent_moves": recent_moves,
        "biggest_move": biggest_move,
        "total_takeovers": side_a["takeovers"] + side_b["takeovers"],
    }
