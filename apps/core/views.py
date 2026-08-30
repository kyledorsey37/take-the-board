from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from apps.boards.models import Board
from apps.schools.services import default_competition


def home(request: HttpRequest) -> HttpResponse:
    boards = Board.objects.filter(entity__competition=default_competition()).select_related("entity", "current_controller").order_by(
        "-current_amount_cents", "entity__name"
    )[:6]
    return render(request, "home.html", {"boards": boards})


def healthz(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})
