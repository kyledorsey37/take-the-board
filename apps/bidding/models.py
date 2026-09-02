import uuid
from decimal import Decimal
from django.conf import settings

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
    confirmation = models.ForeignKey(
        "BidConfirmation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="bids",
    )
    amount_cents = models.PositiveIntegerField()
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.CREATED)
    stripe_checkout_session_id = models.CharField(max_length=255, blank=True)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True)
    stripe_dispute_id = models.CharField(max_length=255, blank=True, unique=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    authorized_at = models.DateTimeField(null=True, blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    payment_failure_count = models.PositiveIntegerField(default=0)
    payment_failed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["board", "-created_at"]),
            models.Index(fields=["bidder", "-created_at"]),
            models.Index(fields=["represented_entity", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["stripe_payment_intent_id"]),
            models.Index(fields=["bidder", "-payment_failed_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.amount_cents} cent bid on {self.board}"

    @property
    def amount_dollars(self) -> Decimal:
        return Decimal(self.amount_cents) / 100


class BidRiskConfig(models.Model):
    """Singleton, operator-controlled risk limits for real-money bidding."""

    new_max_bid_cents = models.PositiveIntegerField(default=5000)
    new_hourly_spend_cents = models.PositiveIntegerField(default=10000)
    new_daily_spend_cents = models.PositiveIntegerField(default=25000)
    established_max_bid_cents = models.PositiveIntegerField(default=10000)
    established_hourly_spend_cents = models.PositiveIntegerField(default=25000)
    established_daily_spend_cents = models.PositiveIntegerField(default=75000)
    trusted_max_bid_cents = models.PositiveIntegerField(default=25000)
    trusted_hourly_spend_cents = models.PositiveIntegerField(default=50000)
    trusted_daily_spend_cents = models.PositiveIntegerField(default=150000)
    global_max_bid_cents = models.PositiveIntegerField(default=25000)
    global_hourly_spend_cents = models.PositiveIntegerField(default=150000)
    high_value_confirmation_threshold_cents = models.PositiveIntegerField(default=5000)
    very_high_value_confirmation_threshold_cents = models.PositiveIntegerField(default=10000)
    high_value_bidding_enabled = models.BooleanField(default=True)
    new_user_bidding_enabled = models.BooleanField(default=True)
    payment_failure_limit = models.PositiveIntegerField(default=5)
    payment_failure_window_minutes = models.PositiveIntegerField(default=30)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "bid risk configuration"
        verbose_name_plural = "bid risk configuration"

    def __str__(self) -> str:
        return "Bid risk configuration"


class BidConfirmation(models.Model):
    """Immutable record of the exact paid-bid confirmation shown to a user."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey("accounts.UserProfile", on_delete=models.PROTECT, related_name="bid_confirmations")
    board = models.ForeignKey("boards.Board", on_delete=models.PROTECT, related_name="bid_confirmations")
    represented_entity = models.ForeignKey("schools.Entity", on_delete=models.PROTECT)
    message_validation = models.ForeignKey("moderation.MessageValidation", on_delete=models.PROTECT)
    message = models.CharField(max_length=80)
    amount_cents = models.PositiveIntegerField()
    current_board_amount_cents = models.PositiveIntegerField()
    pending_challenge_amount_cents = models.PositiveIntegerField(null=True, blank=True)
    minimum_bid_cents = models.PositiveIntegerField()
    guaranteed_seconds = models.PositiveIntegerField(default=30)
    confirmation_version = models.CharField(max_length=50, default="bid-confirmation-v1")
    shown_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    request_id = models.CharField(max_length=64, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-shown_at"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        return f"Confirmation {self.public_id}"

    @property
    def amount_dollars(self) -> Decimal:
        return Decimal(self.amount_cents) / 100

    @property
    def current_board_amount_dollars(self) -> Decimal:
        return Decimal(self.current_board_amount_cents) / 100

    @property
    def pending_challenge_amount_dollars(self) -> Decimal | None:
        if self.pending_challenge_amount_cents is None:
            return None
        return Decimal(self.pending_challenge_amount_cents) / 100

    @property
    def minimum_bid_dollars(self) -> Decimal:
        return Decimal(self.minimum_bid_cents) / 100
