from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import Bid


@admin.register(Bid)
class BidAdmin(ModelAdmin):
    list_display = ("public_id", "board", "bidder", "represented_entity", "amount_cents", "status", "created_at")
    list_filter = ("status", "represented_entity")
    search_fields = (
        "public_id",
        "board__entity__name",
        "bidder__display_name",
        "stripe_checkout_session_id",
        "stripe_payment_intent_id",
    )
    readonly_fields = (
        "public_id",
        "created_at",
        "authorized_at",
        "captured_at",
        "canceled_at",
        "payment_capture_snapshot",
    )

    @admin.display(description="Payment capture snapshot")
    def payment_capture_snapshot(self, obj):
        try:
            capture = obj.payment_capture
        except Bid.payment_capture.RelatedObjectDoesNotExist:
            return "No successful Stripe capture recorded."
        url = reverse("admin:payments_paymentcapture_change", args=[capture.pk])
        if capture.fee_status == "available":
            fee_summary = f"fee ${capture.stripe_fee_cents / 100:.2f}; net ${capture.net_amount_cents / 100:.2f}"
        else:
            fee_summary = "Stripe fee data pending"
        return format_html('<a href="{}">{}</a> ({})', url, "View payment capture", fee_summary)
