from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import LedgerEntry, PaymentCapture, StripeEvent


@admin.register(StripeEvent)
class StripeEventAdmin(ModelAdmin):
    list_display = ("event_id", "event_type", "received_at", "processed_at")
    search_fields = ("event_id", "event_type")
    readonly_fields = ("received_at", "processed_at")


@admin.register(LedgerEntry)
class LedgerEntryAdmin(ModelAdmin):
    list_display = ("type", "amount_cents", "user", "school", "bid", "created_at")
    list_filter = ("type", "school")
    search_fields = ("user__display_name", "school__name", "bid__public_id")
    readonly_fields = ("created_at",)


@admin.register(PaymentCapture)
class PaymentCaptureAdmin(ModelAdmin):
    list_display = (
        "bid",
        "gross_amount_cents",
        "currency",
        "stripe_fee_cents",
        "net_amount_cents",
        "fee_status",
        "captured_at",
    )
    list_filter = ("fee_status", "currency")
    search_fields = (
        "bid__public_id",
        "stripe_payment_intent_id",
        "stripe_charge_id",
        "stripe_balance_transaction_id",
    )
    readonly_fields = (
        "bid",
        "stripe_payment_intent_id",
        "stripe_charge_id",
        "stripe_balance_transaction_id",
        "gross_amount_cents",
        "currency",
        "stripe_fee_cents",
        "net_amount_cents",
        "fee_details",
        "fee_status",
        "captured_at",
        "fee_available_at",
        "fee_reconciliation_attempted_at",
        "fee_reconciliation_attempts",
        "created_at",
    )
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
