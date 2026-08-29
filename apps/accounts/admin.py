from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(ModelAdmin):
    list_display = ("display_name", "email", "favorite_school", "is_banned", "total_spend_cents")
    search_fields = ("display_name", "email", "cognito_sub")
    list_filter = ("is_banned", "favorite_school")
    readonly_fields = ("created_at", "updated_at")
