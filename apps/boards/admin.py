from django.contrib import admin
from django.conf import settings
from unfold.admin import ModelAdmin

from .models import Board, BoardTakeover
from apps.moderation.services.operations import audit_action


@admin.register(Board)
class BoardAdmin(ModelAdmin):
    list_display = (
        "entity",
        "current_controller",
        "current_amount_cents",
        "pending_bid",
        "guaranteed_until",
        "bidding_enabled",
        "updated_at",
    )
    list_filter = ("bidding_enabled",)
    search_fields = ("entity__name", "entity__slug", "current_message")
    readonly_fields = ("version", "updated_at")
    actions = ("disable_selected_boards", "remove_selected_current_messages")

    @admin.action(description="Disable bidding on selected boards")
    def disable_selected_boards(self, request, queryset):
        for board in queryset.filter(bidding_enabled=True):
            board.bidding_enabled = False
            board.save(update_fields=["bidding_enabled", "updated_at"])
            audit_action(actor=request.user, action="disable_bidding", target=board, reason="Django Admin action")

    @admin.action(description="Remove selected current messages")
    def remove_selected_current_messages(self, request, queryset):
        for board in queryset.exclude(current_message=settings.TAKEBOARD_DEFAULT_BOARD_MESSAGE):
            board.current_message = settings.TAKEBOARD_DEFAULT_BOARD_MESSAGE
            board.save(update_fields=["current_message", "updated_at"])
            audit_action(actor=request.user, action="remove_current_message", target=board, reason="Django Admin action")


@admin.register(BoardTakeover)
class BoardTakeoverAdmin(ModelAdmin):
    list_display = (
        "board",
        "controller_display_name",
        "represented_entity",
        "amount_cents",
        "occurred_at",
    )
    list_filter = ("represented_entity",)
    search_fields = ("board__entity__name", "controller__display_name", "message")
    readonly_fields = ("occurred_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    actions = ()
