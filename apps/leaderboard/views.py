from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.schools.services import default_competition

from .services import build_leaderboard
from .week_services import weekly_reset_schedule


def leaderboard(request: HttpRequest) -> HttpResponse:
    data = build_leaderboard(request.GET.get("period", "all"))
    reset_schedule = weekly_reset_schedule(competition=default_competition())
    data.update(
        {
            "round_status_enabled": True,
            "round_status_surface": "standings",
            "round_reset_at": reset_schedule.reset_at,
            "round_server_now": reset_schedule.server_now,
            "round_is_due": reset_schedule.is_due,
            "current_week_number": reset_schedule.week_number,
        }
    )
    return render(request, "leaderboard.html", data)
