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
