from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import DisplayNameValidation, MessageValidation, ModerationActionAudit


@admin.register(MessageValidation)
class MessageValidationAdmin(ModelAdmin):
    list_display = ("public_id", "user", "board", "represented_school", "decision", "category", "expires_at")
    list_filter = ("decision", "category", "represented_school", "expires_at")
    search_fields = ("public_id", "user__display_name", "board__school__name", "message_hash")
    readonly_fields = ("public_id", "created_at", "consumed_at", "message_hash", "policy_version", "classifier_version")


@admin.register(DisplayNameValidation)
class DisplayNameValidationAdmin(ModelAdmin):
    list_display = ("public_id", "user", "decision", "category", "expires_at")
    list_filter = ("decision", "category", "expires_at")
    search_fields = ("public_id", "user__display_name", "candidate_hash")
    readonly_fields = ("public_id", "created_at", "consumed_at", "candidate_hash", "policy_version", "classifier_version")


@admin.register(ModerationActionAudit)
class ModerationActionAuditAdmin(ModelAdmin):
    list_display = ("action", "target_type", "target_id", "actor", "created_at")
    list_filter = ("action", "target_type")
    search_fields = ("target_id", "reason", "actor__username")
    readonly_fields = ("actor", "target_type", "target_id", "action", "reason", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
