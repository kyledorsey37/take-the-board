from django.db import models


class StripeEvent(models.Model):
    event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["event_type", "-received_at"]),
            models.Index(fields=["processed_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} ({self.event_id})"


class LedgerEntry(models.Model):
    class Type(models.TextChoices):
        BID_CAPTURE = "bid_capture", "Bid capture"
        REFUND = "refund", "Refund"
        CHARGEBACK = "chargeback", "Chargeback"
        ADJUSTMENT = "adjustment", "Adjustment"

    type = models.CharField(max_length=30, choices=Type.choices)
    amount_cents = models.IntegerField()
    user = models.ForeignKey("accounts.UserProfile", null=True, blank=True, on_delete=models.SET_NULL)
    school = models.ForeignKey("schools.School", null=True, blank=True, on_delete=models.SET_NULL)
    bid = models.ForeignKey("bidding.Bid", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["school", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["bid"]),
            models.Index(fields=["type", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.type}: {self.amount_cents}"
