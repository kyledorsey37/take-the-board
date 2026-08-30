from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import UserProfile
from apps.moderation.services.operations import audit_action


@admin.register(UserProfile)
class UserProfileAdmin(ModelAdmin):
    list_display = ("display_name", "email", "favorite_entity", "is_banned", "total_spend_cents")
    search_fields = ("display_name", "email", "cognito_sub")
    list_filter = ("is_banned", "favorite_entity")
    readonly_fields = ("created_at", "updated_at")

    actions = ("ban_selected_users", "clear_selected_display_names")

    @admin.action(description="Ban selected users")
    def ban_selected_users(self, request, queryset):
        for profile in queryset.exclude(is_banned=True):
            profile.is_banned = True
            profile.save(update_fields=["is_banned", "updated_at"])
            audit_action(actor=request.user, action="ban_user", target=profile, reason="Django Admin action")

    @admin.action(description="Clear selected display names")
    def clear_selected_display_names(self, request, queryset):
        for profile in queryset.exclude(display_name__isnull=True):
            profile.display_name = None
            profile.save(update_fields=["display_name", "updated_at"])
            audit_action(actor=request.user, action="clear_display_name", target=profile, reason="Django Admin action")
