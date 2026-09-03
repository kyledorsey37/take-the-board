"""Read-only data assembly for the Django Admin operations home."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.boards.models import Board, BoardTakeover
from apps.bidding.models import Bid
from apps.moderation.models import (
    MessageReportCase,
    MessageValidation,
    ModerationPaymentAction,
)
from apps.payments.models import LedgerEntry, PaymentCapture


WINDOW_DAYS = 30
CHART_HEIGHT = 112
CHART_BASELINE = 132
CHART_LEFT = 8
CHART_RIGHT = 292


def _money(cents: int | None) -> str:
    return f"${Decimal(cents or 0) / Decimal(100):,.2f}"


def _start_of_day(day: date) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.min))


def _change(current: int, previous: int) -> dict[str, str]:
    if previous == 0:
        if current == 0:
            return {"label": "No change", "tone": "neutral"}
        return {"label": "New activity", "tone": "positive"}
    percentage = round(((current - previous) / previous) * 100)
    if percentage == 0:
        return {"label": "Flat vs prior", "tone": "neutral"}
    return {
        "label": f"{'+' if percentage > 0 else ''}{percentage}% vs prior",
        "tone": "positive" if percentage > 0 else "negative",
    }


def _line_chart(values: list[int], labels: list[str], formatter) -> dict[str, str]:
    maximum = max(values, default=0)
    scale = maximum or 1
    if len(values) == 1:
        x_values = [150]
    else:
        x_values = [CHART_LEFT + (CHART_RIGHT - CHART_LEFT) * index / (len(values) - 1) for index in range(len(values))]
    points = []
    for x, value in zip(x_values, values):
        y = CHART_BASELINE - (value / scale) * CHART_HEIGHT
        points.append(f"{x:.1f},{y:.1f}")
    peak_index = values.index(maximum) if maximum else 0
    return {
        "points": " ".join(points),
        "maximum": formatter(maximum),
        "peak_label": labels[peak_index] if labels else "",
        "start_label": labels[0] if labels else "",
        "end_label": labels[-1] if labels else "",
        "aria_label": f"{formatter(maximum)} peak on {labels[peak_index] if labels else 'this period'}",
    }


def _bar_height(value: int, maximum: int) -> str:
    if not value or not maximum:
        return "0"
    return f"{max(8, round(value / maximum * 100))}"


def _can_view(user, app_label: str, model_name: str) -> bool:
    return user.is_superuser or user.has_perm(f"{app_label}.view_{model_name}")


def _url(name: str, query: str = "") -> str:
    return f"{reverse(name)}{query}"


def build_admin_dashboard(request) -> dict:
    """Build an admin-only, aggregate view of operational activity."""
    user = request.user
    now = timezone.now()
    today = timezone.localdate(now)

    can_users = _can_view(user, "accounts", "userprofile")
    can_bids = _can_view(user, "bidding", "bid")
    can_takeovers = _can_view(user, "boards", "boardtakeover")
    can_payments = _can_view(user, "payments", "paymentcapture")
    can_reports = _can_view(user, "moderation", "messagereportcase")
    can_validation = _can_view(user, "moderation", "messagevalidation")
    can_payment_actions = _can_view(user, "moderation", "moderationpaymentaction")

    day_list = [today - timedelta(days=index) for index in range(WINDOW_DAYS - 1, -1, -1)]
    day_labels = [day.strftime("%b %-d") for day in day_list]
    period_start = _start_of_day(day_list[0])
    period_end = _start_of_day(today + timedelta(days=1))
    current_start = period_start
    previous_start = current_start - timedelta(days=WINDOW_DAYS)

    capture_daily = {}
    if can_payments:
        capture_daily = {
            row["day"]: row["total"] or 0
            for row in PaymentCapture.objects.filter(
                captured_at__gte=period_start,
                captured_at__lt=period_end,
            )
            .annotate(day=TruncDate("captured_at", tzinfo=timezone.get_current_timezone()))
            .values("day")
            .annotate(total=Sum("gross_amount_cents"))
        }

    bid_daily = {}
    if can_bids:
        bid_daily = {
            row["day"]: row["total"]
            for row in Bid.objects.filter(created_at__gte=period_start, created_at__lt=period_end)
            .annotate(day=TruncDate("created_at", tzinfo=timezone.get_current_timezone()))
            .values("day")
            .annotate(total=Count("id"))
        }

    takeover_daily = {}
    if can_takeovers:
        takeover_daily = {
            row["day"]: row["total"]
            for row in BoardTakeover.objects.filter(occurred_at__gte=period_start, occurred_at__lt=period_end)
            .annotate(day=TruncDate("occurred_at", tzinfo=timezone.get_current_timezone()))
            .values("day")
            .annotate(total=Count("id"))
        }

    user_daily = {}
    if can_users:
        user_daily = {
            row["day"]: row["total"]
            for row in UserProfile.objects.filter(created_at__gte=period_start, created_at__lt=period_end)
            .annotate(day=TruncDate("created_at", tzinfo=timezone.get_current_timezone()))
            .values("day")
            .annotate(total=Count("id"))
        }

    active_bidders_daily = {}
    if can_bids:
        active_bidders_daily = {
            row["day"]: row["total"]
            for row in Bid.objects.filter(created_at__gte=period_start, created_at__lt=period_end)
            .annotate(day=TruncDate("created_at", tzinfo=timezone.get_current_timezone()))
            .values("day")
            .annotate(total=Count("bidder", distinct=True))
        }

    daily_volume = [capture_daily.get(day, 0) for day in day_list]
    daily_bids = [bid_daily.get(day, 0) for day in day_list]
    daily_takeovers = [takeover_daily.get(day, 0) for day in day_list]
    daily_users = [user_daily.get(day, 0) for day in day_list]
    daily_active_bidders = [active_bidders_daily.get(day, 0) for day in day_list]

    current_volume = sum(daily_volume)
    current_bids = sum(daily_bids)
    current_takeovers = sum(daily_takeovers)
    current_users = sum(daily_users)
    previous_volume = 0
    previous_bids = 0
    previous_takeovers = 0
    previous_users = 0
    if can_payments:
        previous_volume = PaymentCapture.objects.filter(
            captured_at__gte=previous_start,
            captured_at__lt=current_start,
        ).aggregate(total=Sum("gross_amount_cents"))["total"] or 0
    if can_bids:
        previous_bids = Bid.objects.filter(created_at__gte=previous_start, created_at__lt=current_start).count()
    if can_takeovers:
        previous_takeovers = BoardTakeover.objects.filter(
            occurred_at__gte=previous_start,
            occurred_at__lt=current_start,
        ).count()
    if can_users:
        previous_users = UserProfile.objects.filter(
            created_at__gte=previous_start,
            created_at__lt=current_start,
        ).count()

    action_items = []
    if can_reports:
        open_reports = MessageReportCase.objects.filter(status=MessageReportCase.Status.OPEN)
        open_report_count = open_reports.count()
        action_items.append({
            "eyebrow": "Moderation",
            "title": "Resolve reported messages",
            "detail": "Open cases waiting for an approve or remove decision.",
            "count": open_report_count,
            "count_label": "case" if open_report_count == 1 else "cases",
            "tone": "urgent" if open_report_count else "quiet",
            "url": _url("admin:moderation_messagereportcase_changelist", "?status__exact=open"),
        })
    if can_validation:
        review_count = MessageValidation.objects.filter(
            decision=MessageValidation.Decision.REVIEW,
            expires_at__gte=now,
        ).count()
        blocked_count = MessageValidation.objects.filter(
            decision=MessageValidation.Decision.BLOCK,
            created_at__gte=now - timedelta(days=7),
        ).count()
        action_items.extend([
            {
                "eyebrow": "Moderation",
                "title": "Review flagged messages",
                "detail": "Automated checks that requested human review.",
                "count": review_count,
                "count_label": "message" if review_count == 1 else "messages",
                "tone": "attention" if review_count else "quiet",
                "url": _url("admin:moderation_messagevalidation_changelist", "?decision__exact=review"),
            },
            {
                "eyebrow": "Moderation audit",
                "title": "Audit recent blocks",
                "detail": "Blocked validations created in the last seven days.",
                "count": blocked_count,
                "count_label": "block" if blocked_count == 1 else "blocks",
                "tone": "attention" if blocked_count else "quiet",
                "url": _url("admin:moderation_messagevalidation_changelist", "?decision__exact=block"),
            },
        ])
    if can_payment_actions:
        payment_exception_count = ModerationPaymentAction.objects.filter(
            status__in=[ModerationPaymentAction.Status.PENDING, ModerationPaymentAction.Status.FAILED]
        ).count()
        action_items.append({
            "eyebrow": "Payments",
            "title": "Settle payment exceptions",
            "detail": "Refund or cancellation work that needs attention.",
            "count": payment_exception_count,
            "count_label": "item" if payment_exception_count == 1 else "items",
            "tone": "attention" if payment_exception_count else "quiet",
            "url": _url("admin:moderation_moderationpaymentaction_changelist"),
        })
    if can_payments:
        fee_pending_count = PaymentCapture.objects.filter(fee_status=PaymentCapture.FeeStatus.PENDING).count()
        action_items.append({
            "eyebrow": "Reconciliation",
            "title": "Reconcile Stripe fees",
            "detail": "Captured payments still waiting for fee data.",
            "count": fee_pending_count,
            "count_label": "capture" if fee_pending_count == 1 else "captures",
            "tone": "attention" if fee_pending_count else "quiet",
            "url": _url("admin:payments_paymentcapture_changelist", "?fee_status__exact=pending"),
        })

    recent_cases = []
    if can_reports:
        recent_cases = [
            {
                "school": case.takeover.board.entity.name,
                "reported_at": timezone.localtime(case.last_reported_at).strftime("%b %-d, %-I:%M %p"),
                "report_count": case.reports.count(),
                "url": reverse("admin:moderation_messagereportcase_change", args=[case.pk]),
            }
            for case in MessageReportCase.objects.filter(status=MessageReportCase.Status.OPEN)
            .select_related("takeover__board__entity")
            .prefetch_related("reports")
            .order_by("-last_reported_at")[:4]
        ]

    top_schools = []
    if can_takeovers:
        top_rows = list(
            BoardTakeover.objects.filter(occurred_at__gte=current_start)
            .values("board__entity__name")
            .annotate(volume=Sum("amount_cents"), takeovers=Count("id"))
            .order_by("-volume", "board__entity__name")[:5]
        )
        maximum = max((row["volume"] or 0 for row in top_rows), default=0)
        top_schools = [
            {
                "name": row["board__entity__name"],
                "volume": _money(row["volume"]),
                "takeovers": row["takeovers"],
                "height": _bar_height(row["volume"] or 0, maximum),
            }
            for row in top_rows
        ]

    quick_links = []
    if can_reports:
        quick_links.append({"label": "Review reports", "detail": "Moderation queue", "url": _url("admin:moderation_messagereportcase_changelist")})
    if can_bids:
        quick_links.append({"label": "View bids", "detail": "Payment and bid states", "url": _url("admin:bidding_bid_changelist")})
    if can_users:
        quick_links.append({"label": "Browse users", "detail": "Accounts and risk tiers", "url": _url("admin:accounts_userprofile_changelist")})
    if _can_view(user, "core", "activity"):
        quick_links.append({"label": "Open activity", "detail": "Recent system events", "url": _url("admin:core_activity_changelist")})

    return {
        "generated_at": timezone.localtime(now),
        "window_days": WINDOW_DAYS,
        "action_items": action_items,
        "recent_cases": recent_cases,
        "top_schools": top_schools,
        "has_action_items": bool(action_items),
        "has_reporting": can_bids or can_takeovers or can_payments or can_users,
        "metrics": {
            "captured_volume": _money(current_volume),
            "captured_volume_change": _change(current_volume, previous_volume),
            "bid_count": f"{current_bids:,}",
            "bid_count_change": _change(current_bids, previous_bids),
            "takeover_count": f"{current_takeovers:,}",
            "takeover_count_change": _change(current_takeovers, previous_takeovers),
            "new_users": f"{current_users:,}",
            "new_users_change": _change(current_users, previous_users),
            "active_bidders": f"{sum(daily_active_bidders):,}",
        },
        "permissions": {
            "users": can_users,
            "bids": can_bids,
            "takeovers": can_takeovers,
            "payments": can_payments,
        },
        "charts": {
            "volume": _line_chart(daily_volume, day_labels, _money),
            "bids": _line_chart(daily_bids, day_labels, lambda value: f"{value:,}"),
            "users": _line_chart(daily_users, day_labels, lambda value: f"{value:,}"),
            "takeovers": _line_chart(daily_takeovers, day_labels, lambda value: f"{value:,}"),
        },
        "quick_links": quick_links,
    }
