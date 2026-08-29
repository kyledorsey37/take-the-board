from django.urls import path

from . import views


app_name = "boards"

urlpatterns = [
    path("boards/", views.board_index, name="index"),
]
