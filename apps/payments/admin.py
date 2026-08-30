from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import LedgerEntry, PaymentCapture, PurchaseEvidence, StripeEvent


@admin.register(StripeEvent)
class StripeEventAdmin(ModelAdmin):
    list_display = ("event_id", "event_type", "received_at", "processed_at")
    search_fields = ("event_id", "event_type")
    readonly_fields = ("received_at", "processed_at")


@admin.register(LedgerEntry)
class LedgerEntryAdmin(ModelAdmin):
    list_display = ("type", "amount_cents", "user", "entity", "bid", "created_at")
    list_filter = ("type", "entity")
    search_fields = ("user__display_name", "entity__name", "bid__public_id")
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


@admin.register(PurchaseEvidence)
class PurchaseEvidenceAdmin(ModelAdmin):
    list_display = ("bid", "display_name", "board_name", "risk_tier_at_purchase", "published_at", "guaranteed_until", "ended_at")
    search_fields = ("bid__public_id", "cognito_sub", "email", "display_name", "board_name")
    readonly_fields = tuple(field.name for field in PurchaseEvidence._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
