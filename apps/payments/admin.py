from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import LedgerEntry, StripeEvent


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
