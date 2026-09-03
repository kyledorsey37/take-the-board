from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import EmailOutbox


@admin.register(EmailOutbox)
class EmailOutboxAdmin(ModelAdmin):
    list_display = (
        "created_at",
        "kind",
        "status",
        "attempts",
        "last_error_code",
        "sent_at",
    )
    list_filter = ("kind", "status", "created_at", "sent_at")
    search_fields = ("event_key", "recipient_email", "provider_message_id")
    readonly_fields = tuple(field.name for field in EmailOutbox._meta.fields)
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    actions = ()

