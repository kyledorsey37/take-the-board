import uuid

from django.db import models


class MessageValidation(models.Model):
    class Decision(models.TextChoices):
        ALLOW = "allow", "Allow"
        BLOCK = "block", "Block"
        REVIEW = "review", "Review"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey("accounts.UserProfile", on_delete=models.CASCADE)
    board = models.ForeignKey("boards.Board", on_delete=models.CASCADE)
    represented_school = models.ForeignKey("schools.School", on_delete=models.PROTECT)
    message = models.CharField(max_length=80)
    message_hash = models.CharField(max_length=64)
    decision = models.CharField(max_length=20, choices=Decision.choices)
    category = models.CharField(max_length=50, blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    policy_version = models.CharField(max_length=32, default="")
    classifier_version = models.CharField(max_length=64, default="")
    content_retention_until = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["board", "-created_at"]),
            models.Index(fields=["decision", "-created_at"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.decision} validation for {self.board}"


class DisplayNameValidation(models.Model):
    class Decision(models.TextChoices):
        ALLOW = "allow", "Allow"
        BLOCK = "block", "Block"
        REVIEW = "review", "Review"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey("accounts.UserProfile", on_delete=models.CASCADE)
    display_name = models.CharField(max_length=40, blank=True)
    candidate_hash = models.CharField(max_length=64)
    decision = models.CharField(max_length=20, choices=Decision.choices)
    category = models.CharField(max_length=50, blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    policy_version = models.CharField(max_length=32)
    classifier_version = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    content_retention_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["decision", "-created_at"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.decision} display-name validation for {self.user_id}"


class ModerationActionAudit(models.Model):
    actor = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="moderation_actions"
    )
    target_type = models.CharField(max_length=40)
    target_id = models.CharField(max_length=64)
    action = models.CharField(max_length=64)
    reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.action} {self.target_type}:{self.target_id}"
