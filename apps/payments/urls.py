from django.urls import path

from . import views


app_name = "payments"

urlpatterns = [
    path(
        "api/payments/bids/<uuid:public_id>/status/",
        views.bid_status,
        name="bid_status",
    ),
    path("webhooks/stripe/", views.stripe_webhook, name="stripe_webhook"),
]
