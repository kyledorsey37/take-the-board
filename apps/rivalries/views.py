from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.leaderboard.week_services import weekly_reset_schedule
from apps.schools.services import default_competition

from .models import Rivalry
from .services import build_rivalry_scoreboard


def _round_status_context(*, surface: str) -> dict:
    reset_schedule = weekly_reset_schedule(competition=default_competition())
    return {
        "round_status_enabled": True,
        "round_status_surface": surface,
        "round_reset_at": reset_schedule.reset_at,
        "round_server_now": reset_schedule.server_now,
        "round_is_due": reset_schedule.is_due,
        "current_week_number": reset_schedule.week_number,
    }


def rivalry_index(request: HttpRequest) -> HttpResponse:
    rivalries = Rivalry.objects.filter(active=True).select_related("entity_a", "entity_b")
    cards = [build_rivalry_scoreboard(rivalry) for rivalry in rivalries]
    return render(
        request,
        "rivalries/index.html",
        {"rivalry_cards": cards, **_round_status_context(surface="rivalry_directory")},
    )


def rivalry_detail(request: HttpRequest, slug: str) -> HttpResponse:
    rivalry = get_object_or_404(
        Rivalry.objects.filter(active=True).select_related("entity_a", "entity_b"),
        slug=slug,
    )
    scoreboard = build_rivalry_scoreboard(rivalry, request.GET.get("period", "all"))
    scoreboard.update(_round_status_context(surface="rivalry_detail"))
    return render(request, "rivalries/detail.html", scoreboard)
