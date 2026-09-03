from django.db import models
from django.utils import timezone


class EmailOutbox(models.Model):
    """Durable, provider-independent record of one customer email intent."""

    class Kind(models.TextChoices):
        MESSAGE_REMOVED = "message_removed", "Message removed"
        REFUND_CONFIRMATION = "refund_confirmation", "Refund confirmation"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SUPPRESSED = "suppressed", "Suppressed"

    event_key = models.CharField(max_length=180, unique=True)
    kind = models.CharField(max_length=40, choices=Kind.choices)
    recipient_email = models.EmailField()
    context = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now)
    waiting_for_refund = models.BooleanField(default=False)
    locked_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=80, blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "available_at"]),
            models.Index(fields=["status", "locked_at"]),
            models.Index(fields=["kind", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.kind} email ({self.status})"
