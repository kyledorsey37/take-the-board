from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Bid


@admin.register(Bid)
class BidAdmin(ModelAdmin):
    list_display = ("public_id", "board", "bidder", "represented_school", "amount_cents", "status", "created_at")
    list_filter = ("status", "represented_school")
    search_fields = (
        "public_id",
        "board__school__name",
        "bidder__display_name",
        "stripe_checkout_session_id",
        "stripe_payment_intent_id",
    )
    readonly_fields = ("public_id", "created_at", "authorized_at", "captured_at", "canceled_at")
