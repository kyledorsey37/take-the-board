from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from apps.boards.models import Board


def home(request: HttpRequest) -> HttpResponse:
    boards = Board.objects.select_related("school", "current_controller").order_by(
        "-current_amount_cents", "school__name"
    )[:6]
    return render(request, "home.html", {"boards": boards})


def healthz(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})
