from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from apps.accounts.services.session import get_authenticated_profile
from apps.bidding.services.rules import current_board_rules, minimum_takeover_cents
from apps.boards.models import Board
from apps.schools.services import default_competition, safe_accent_color
from apps.core.services.home_hero import home_hero_variant
from apps.core.services.home_board import most_active_board, most_active_board_for


def home(request: HttpRequest) -> HttpResponse:
    boards = (
        Board.objects.filter(entity__competition=default_competition())
        .select_related("entity", "current_controller")
        .order_by("-current_amount_cents", "entity__name")[:6]
    )
    profile = get_authenticated_profile(request)
    hero_variant = home_hero_variant(request)
    featured_board = most_active_board_for(profile) if profile else None
    featured_reason = "Most active for you" if featured_board else "Most active right now"
    if not featured_board:
        featured_board = most_active_board()
    featured_minimum_takeover_dollars = None
    featured_board_accent = "#b3262f"
    if featured_board:
        featured_board_accent = safe_accent_color(featured_board.entity.accent_color)
        pending_amount_cents = (
            featured_board.pending_bid.amount_cents if featured_board.pending_bid_id else 0
        )
        featured_minimum_takeover_dollars = minimum_takeover_cents(
            featured_board.current_amount_cents,
            current_board_rules(),
            pending_amount_cents,
        ) / 100

    return render(
        request,
        "home.html",
        {
            "boards": boards,
            "featured_board": featured_board,
            "featured_reason": featured_reason,
            "featured_minimum_takeover_dollars": featured_minimum_takeover_dollars,
            "featured_board_accent": featured_board_accent,
            "hero_variant": hero_variant,
        },
    )


def how_it_works(request: HttpRequest) -> HttpResponse:
    return render(request, "how_it_works.html")


def healthz(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})
