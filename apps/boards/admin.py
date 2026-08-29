from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Board, BoardTakeover


@admin.register(Board)
class BoardAdmin(ModelAdmin):
    list_display = (
        "school",
        "current_controller",
        "current_amount_cents",
        "pending_bid",
        "guaranteed_until",
        "bidding_enabled",
        "updated_at",
    )
    list_filter = ("bidding_enabled",)
    search_fields = ("school__name", "school__slug", "current_message")
    readonly_fields = ("version", "updated_at")


@admin.register(BoardTakeover)
class BoardTakeoverAdmin(ModelAdmin):
    list_display = (
        "board",
        "controller_display_name",
        "represented_school",
        "amount_cents",
        "occurred_at",
    )
    list_filter = ("represented_school",)
    search_fields = ("board__school__name", "controller__display_name", "message")
    readonly_fields = ("occurred_at",)
