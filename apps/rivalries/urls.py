from django.urls import path

from . import views


app_name = "rivalries"

urlpatterns = [
    path("rivalries/", views.rivalry_index, name="index"),
    path("rivalries/<slug:slug>/", views.rivalry_detail, name="detail"),
]
