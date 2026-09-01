from decimal import Decimal

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone

from apps.bidding.forms import TakeBoardForm
from apps.bidding.services.finalize_bid import finalize_due_board
from apps.bidding.services.rules import current_board_rules, minimum_takeover_cents
from apps.boards.models import Board
from apps.boards.models import BoardTakeover
from apps.moderation.models import MessageReport, MessageReportCase
from apps.accounts.services.session import get_authenticated_profile
from apps.core.services.home_board import record_board_visit
from apps.leaderboard.week_services import current_period_window, weekly_reset_schedule
from .models import Entity
from .services import default_competition, safe_accent_color


def _group_takeovers_by_week(takeovers: list[BoardTakeover]) -> list[dict]:
    """Build ordered public history groups from persisted competition weeks."""
    groups: dict[object, dict] = {}
    for takeover in takeovers:
        if takeover.period_id and takeover.period:
            starts_at = takeover.period.starts_at
            ends_at = takeover.period.ends_at
            is_current = takeover.period.active
        else:
            window = current_period_window(takeover.occurred_at)
            starts_at = window.starts_at
            ends_at = window.ends_at
            is_current = starts_at <= timezone.now() < ends_at
        group_key = ("week", starts_at)

        group = groups.setdefault(
            group_key,
            {
                "starts_at": starts_at,
                "ends_at": ends_at,
                "is_current": is_current,
                "takeovers": [],
            },
        )
        group["takeovers"].append(takeover)
        group["is_current"] = group["is_current"] or is_current

    grouped = list(groups.values())
    for index, group in enumerate(grouped):
        group["is_latest"] = index == 0
        group["count_label"] = "takeover" if len(group["takeovers"]) == 1 else "takeovers"
    return grouped


def school_detail(request: HttpRequest, slug: str) -> HttpResponse:
    competition = default_competition()
    authenticated_profile = get_authenticated_profile(request)
    initial_board = get_object_or_404(
        Board,
        entity__competition=competition,
        entity__slug=slug,
        entity__active=True,
    )
    if authenticated_profile:
        record_board_visit(profile=authenticated_profile, board=initial_board)
    rules = current_board_rules()
    if settings.TAKEBOARD_DEMO_BIDDING_ENABLED:
        finalize_due_board(board_id=initial_board.id, rules=rules)

    board = get_object_or_404(
        Board.objects.select_related(
            "entity",
            "current_controller",
            "current_bid__represented_entity",
            "pending_bid__represented_entity",
        ),
        entity__competition=competition,
        entity__slug=slug,
        entity__active=True,
    )
    entity_accent = safe_accent_color(board.entity.accent_color)
    pending_amount_cents = board.pending_bid.amount_cents if board.pending_bid_id else 0
    minimum_takeover = minimum_takeover_cents(
        board.current_amount_cents,
        rules,
        pending_amount_cents,
    )
    quick_bids = []
    for amount in (
        Decimal(minimum_takeover) / 100,
        Decimal(max(minimum_takeover, 500)) / 100,
        Decimal(max(minimum_takeover, 1000)) / 100,
        Decimal(max(minimum_takeover, 2500)) / 100,
    ):
        if amount not in quick_bids:
            quick_bids.append(amount)
    authenticated_player_ready = bool(authenticated_profile and authenticated_profile.display_name)
    selected_represented_entity = board.entity
    backing_slug = request.GET.get("backing", "").strip()
    if backing_slug:
        selected_represented_entity = (
            Entity.objects.filter(competition=competition, slug=backing_slug, active=True).first()
            or selected_represented_entity
        )
    form = TakeBoardForm(
        rules=rules,
        competition=competition,
        require_display_name=not bool(
            settings.TAKEBOARD_REQUIRE_AUTH_FOR_BIDDING and authenticated_player_ready
        ),
        require_age_acknowledgement=bool(
            settings.TAKEBOARD_STRIPE_ENABLED
            and authenticated_profile
            and not authenticated_profile.has_age_acknowledgement
        ),
        initial={
            "board_slug": board.entity.slug,
            "amount": f"{minimum_takeover / 100:.2f}",
            "represented_entity": selected_represented_entity.id,
        },
    )
    takeovers = list(
        board.takeovers.select_related("represented_entity", "report_case", "period")
        .order_by("-occurred_at", "-id")
    )
    current_takeover = None
    if board.current_bid_id:
        current_takeover = (
            BoardTakeover.objects.select_related("represented_entity", "report_case")
            .filter(board=board, bid_id=board.current_bid_id)
            .first()
        )
    for takeover in takeovers + ([current_takeover] if current_takeover else []):
        report_case = getattr(takeover, "report_case", None)
        takeover.report_status = report_case.status if report_case else ""
        takeover.reporting_closed = bool(
            report_case and report_case.status != MessageReportCase.Status.OPEN
        )
    auth_modal_enabled = (
        settings.TAKEBOARD_COGNITO_AUTH_ENABLED
        or settings.TAKEBOARD_AUTH_MODAL_PREVIEW
    )
    auth_required_for_bidding = (
        settings.TAKEBOARD_REQUIRE_AUTH_FOR_BIDDING
        or settings.TAKEBOARD_AUTH_MODAL_PREVIEW
    )
    bidding_enabled = bool(
        (settings.TAKEBOARD_DEMO_BIDDING_ENABLED or settings.TAKEBOARD_STRIPE_ENABLED)
        and board.bidding_enabled
    )
    board_url = request.build_absolute_uri(
        reverse("schools:detail", kwargs={"slug": board.entity.slug})
    )
    social_image_url = request.build_absolute_uri(
        reverse("boards:social_image", kwargs={"slug": board.entity.slug})
    ) + f"?v={board.version}"
    social_title = f'{board.entity.name} board: “{board.current_message}” | Take the Board'
    social_description = (
        f"{board.entity.name}'s live fan board. See the current message and take it over "
        "with your next move."
    )
    reset_schedule = weekly_reset_schedule(competition=competition)
    return render(
        request,
        "boards/school_detail.html",
        {
            "board": board,
            "entity_accent": entity_accent,
            "form": form,
            "takeovers": takeovers,
            "takeover_week_groups": _group_takeovers_by_week(takeovers),
            "current_takeover": current_takeover,
            "report_categories": MessageReport.Category.choices,
            "minimum_takeover_dollars": minimum_takeover / 100,
            "quick_bids": quick_bids,
            "message_max_length": rules.message_max_length,
            "demo_bidding_enabled": settings.TAKEBOARD_DEMO_BIDDING_ENABLED,
            "stripe_enabled": settings.TAKEBOARD_STRIPE_ENABLED,
            "stripe_publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
            "bidding_enabled": bidding_enabled,
            "auth_required_for_bidding": auth_required_for_bidding,
            "bidding_modal_enabled": bool(
                bidding_enabled
                and (
                    not auth_required_for_bidding
                    or authenticated_player_ready
                    or not auth_modal_enabled
                )
            ),
            "move_result": request.GET.get("move"),
            "selected_represented_entity": selected_represented_entity,
            "board_url": board_url,
            "social_image_url": social_image_url,
            "social_title": social_title,
            "social_description": social_description,
            "round_status_enabled": True,
            "round_status_surface": "school_board",
            "round_reset_at": reset_schedule.reset_at,
            "round_server_now": reset_schedule.server_now,
            "round_is_due": reset_schedule.is_due,
            "current_week_number": reset_schedule.week_number,
        },
    )
