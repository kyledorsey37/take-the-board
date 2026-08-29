from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from .models import Rivalry
from .services import build_rivalry_scoreboard


def rivalry_index(request: HttpRequest) -> HttpResponse:
    rivalries = Rivalry.objects.filter(active=True).select_related("school_a", "school_b")
    cards = [build_rivalry_scoreboard(rivalry) for rivalry in rivalries]
    return render(request, "rivalries/index.html", {"rivalry_cards": cards})


def rivalry_detail(request: HttpRequest, slug: str) -> HttpResponse:
    rivalry = get_object_or_404(
        Rivalry.objects.filter(active=True).select_related("school_a", "school_b"),
        slug=slug,
    )
    scoreboard = build_rivalry_scoreboard(rivalry, request.GET.get("period", "all"))
    return render(request, "rivalries/detail.html", scoreboard)
