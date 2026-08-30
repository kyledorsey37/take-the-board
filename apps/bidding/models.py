import uuid
from decimal import Decimal

from django.db import models


class Bid(models.Model):
    class Status(models.TextChoices):
        CREATED = "created", "Created"
        MODERATION_APPROVED = "moderation_approved", "Moderation approved"
        CHECKOUT_CREATED = "checkout_created", "Checkout created"
        AUTHORIZED = "authorized", "Authorized"
        PROCESSING = "processing", "Processing"
        WON = "won", "Won"
        DEMO_WON = "demo_won", "Won in local free-play"
        OUTBID = "outbid", "Outbid"
        PAYMENT_FAILED = "payment_failed", "Payment failed"
        AUTH_CANCELED = "auth_canceled", "Authorization canceled"
        REFUNDED = "refunded", "Refunded"
        DISPUTED = "disputed", "Disputed"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    board = models.ForeignKey("boards.Board", on_delete=models.CASCADE, related_name="bids")
    bidder = models.ForeignKey("accounts.UserProfile", on_delete=models.PROTECT, related_name="bids")
    represented_entity = models.ForeignKey(
        "schools.Entity",
        on_delete=models.PROTECT,
        related_name="fan_bids",
    )
    period = models.ForeignKey(
        "leaderboard.CompetitionPeriod",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="bids",
    )
    message = models.CharField(max_length=80)
    message_validation = models.ForeignKey(
        "moderation.MessageValidation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="bids",
    )
    amount_cents = models.PositiveIntegerField()
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.CREATED)
    stripe_checkout_session_id = models.CharField(max_length=255, blank=True)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    authorized_at = models.DateTimeField(null=True, blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["board", "-created_at"]),
            models.Index(fields=["bidder", "-created_at"]),
            models.Index(fields=["represented_entity", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["stripe_payment_intent_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.amount_cents} cent bid on {self.board}"

    @property
    def amount_dollars(self) -> Decimal:
        return Decimal(self.amount_cents) / 100
