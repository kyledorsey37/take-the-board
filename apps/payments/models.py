from django.db import models
from django.utils import timezone


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


class PaymentCapture(models.Model):
    """Immutable provider accounting snapshot for one successful bid capture.

    Stripe can make balance-transaction fees available after the PaymentIntent has
    succeeded.  The capture identity and gross amount are written once; the fee
    fields are filled only when Stripe supplies that delayed accounting data.
    """

    class FeeStatus(models.TextChoices):
        PENDING = "pending", "Pending Stripe fee data"
        AVAILABLE = "available", "Stripe fee data available"

    bid = models.OneToOneField(
        "bidding.Bid",
        on_delete=models.PROTECT,
        related_name="payment_capture",
    )
    stripe_payment_intent_id = models.CharField(max_length=255, unique=True)
    stripe_charge_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    stripe_balance_transaction_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    gross_amount_cents = models.PositiveIntegerField()
    currency = models.CharField(max_length=3)
    stripe_fee_cents = models.PositiveIntegerField(null=True, blank=True)
    net_amount_cents = models.IntegerField(null=True, blank=True)
    fee_details = models.JSONField(default=list, blank=True)
    fee_status = models.CharField(
        max_length=16,
        choices=FeeStatus.choices,
        default=FeeStatus.PENDING,
    )
    captured_at = models.DateTimeField(default=timezone.now)
    fee_available_at = models.DateTimeField(null=True, blank=True)
    fee_reconciliation_attempted_at = models.DateTimeField(null=True, blank=True)
    fee_reconciliation_attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["fee_status", "fee_reconciliation_attempted_at"]),
            models.Index(fields=["-captured_at"]),
        ]

    def __str__(self) -> str:
        return f"Capture for bid {self.bid_id}: {self.gross_amount_cents} {self.currency.upper()}"
