from decimal import Decimal
import re

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.bidding.forms import TakeBoardForm
from apps.bidding.services.finalize_bid import finalize_due_board
from apps.bidding.services.rules import current_board_rules, minimum_takeover_cents
from apps.boards.models import Board
from apps.accounts.services.session import get_authenticated_profile
from .models import School


HEX_COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")


def school_detail(request: HttpRequest, slug: str) -> HttpResponse:
    authenticated_profile = get_authenticated_profile(request)
    initial_board = get_object_or_404(Board, school__slug=slug, school__active=True)
    rules = current_board_rules()
    if settings.TAKEBOARD_DEMO_BIDDING_ENABLED:
        finalize_due_board(board_id=initial_board.id, rules=rules)

    board = get_object_or_404(
        Board.objects.select_related(
            "school",
            "current_controller",
            "current_bid__represented_school",
            "pending_bid__represented_school",
        ),
        school__slug=slug,
        school__active=True,
    )
    school_accent = board.school.accent_color
    if not HEX_COLOR_PATTERN.fullmatch(school_accent):
        school_accent = "#b3262f"
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
    selected_represented_school = board.school
    backing_slug = request.GET.get("backing", "").strip()
    if backing_slug:
        selected_represented_school = (
            School.objects.filter(slug=backing_slug, active=True).first()
            or selected_represented_school
        )
    form = TakeBoardForm(
        rules=rules,
        require_display_name=not bool(
            settings.TAKEBOARD_REQUIRE_AUTH_FOR_BIDDING and authenticated_player_ready
        ),
        initial={
            "board_slug": board.school.slug,
            "amount": f"{minimum_takeover / 100:.2f}",
            "represented_school": selected_represented_school.id,
        },
    )
    takeovers = board.takeovers.select_related("represented_school").order_by("-occurred_at", "-id")[:5]
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
    return render(
        request,
        "boards/school_detail.html",
        {
            "board": board,
            "school_accent": school_accent,
            "form": form,
            "takeovers": takeovers,
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
            "selected_represented_school": selected_represented_school,
        },
    )
