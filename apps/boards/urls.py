from django.urls import path

from . import views


app_name = "boards"

urlpatterns = [
    path("boards/", views.board_index, name="index"),
    path("social/boards/<slug:slug>/card.png", views.board_social_image, name="social_image"),
    path(
        "api/boards/takeovers/<uuid:takeover_public_id>/report/",
        views.report_takeover,
        name="report_takeover",
    ),
]
