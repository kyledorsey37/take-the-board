from django.urls import path

from . import views


app_name = "bidding"

urlpatterns = [
    path("bids/take/", views.take_board, name="take"),
    path("bids/confirm/<uuid:public_id>/", views.confirm_bid, name="confirm"),
]
