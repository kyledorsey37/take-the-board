from django.urls import path

from . import views


app_name = "bidding"

urlpatterns = [
    path("bids/take/", views.take_board, name="take"),
]
