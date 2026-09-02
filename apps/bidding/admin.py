from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from apps.moderation.services.operations import audit_action

from .models import Bid, BidConfirmation, BidRiskConfig


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
        "stripe_dispute_id",
    )
    readonly_fields = (
        "public_id",
        "created_at",
        "authorized_at",
        "captured_at",
        "canceled_at",
        "payment_capture_snapshot",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    actions = ()

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


@admin.register(BidRiskConfig)
class BidRiskConfigAdmin(ModelAdmin):
    list_display = ("new_max_bid_cents", "established_max_bid_cents", "trusted_max_bid_cents", "global_max_bid_cents", "high_value_bidding_enabled", "new_user_bidding_enabled", "updated_at")

    def has_add_permission(self, request):
        return not BidRiskConfig.objects.exists()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        audit_action(actor=request.user, action="update_bid_risk_config", target=obj, reason="Django Admin action")


@admin.register(BidConfirmation)
class BidConfirmationAdmin(ModelAdmin):
    list_display = ("public_id", "user", "board", "amount_cents", "confirmation_version", "shown_at", "confirmed_at", "consumed_at")
    list_filter = ("confirmation_version", "shown_at", "confirmed_at")
    search_fields = ("public_id", "user__display_name", "board__entity__name")
    readonly_fields = tuple(field.name for field in BidConfirmation._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    actions = ()
