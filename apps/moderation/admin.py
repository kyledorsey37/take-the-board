from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import MessageValidation


@admin.register(MessageValidation)
class MessageValidationAdmin(ModelAdmin):
    list_display = ("public_id", "user", "board", "represented_school", "decision", "category", "expires_at")
    list_filter = ("decision", "category", "represented_school")
    search_fields = ("public_id", "user__display_name", "board__school__name", "message_hash")
    readonly_fields = ("public_id", "created_at", "consumed_at")
