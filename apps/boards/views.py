from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from .models import Board


def board_index(request: HttpRequest) -> HttpResponse:
    boards = Board.objects.select_related("school", "current_controller").order_by(
        "-current_amount_cents", "school__name"
    )
    return render(request, "boards/index.html", {"boards": boards})
