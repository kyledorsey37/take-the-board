from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Activity, GameConfig
from apps.moderation.services.operations import audit_action


@admin.register(GameConfig)
class GameConfigAdmin(ModelAdmin):
    @admin.display(description="Configuration")
    def configuration(self, obj: GameConfig) -> str:
        return str(obj)

    list_display = (
        "configuration",
        "minimum_bid_increment_cents",
        "maximum_bid_cents",
        "guaranteed_display_seconds",
        "message_max_length",
        "bidding_enabled",
        "moderation_enabled",
    )
    list_display_links = ("configuration",)

    def has_add_permission(self, request) -> bool:
        return not GameConfig.objects.exists()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        audit_action(actor=request.user, action="update_game_config", target=obj, reason="Django Admin action")


@admin.register(Activity)
class ActivityAdmin(ModelAdmin):
    list_display = ("type", "user", "board", "created_at")
    list_filter = ("type",)
    search_fields = ("type", "user__display_name", "board__entity__name")
    readonly_fields = ("created_at",)
