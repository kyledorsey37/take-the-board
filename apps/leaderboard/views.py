from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from .services import build_leaderboard


def leaderboard(request: HttpRequest) -> HttpResponse:
    data = build_leaderboard(request.GET.get("period", "all"))
    return render(request, "leaderboard.html", data)
