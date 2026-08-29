from django.conf import settings
from django.db import models
from decimal import Decimal


class Board(models.Model):
    school = models.OneToOneField(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="board",
    )
    current_bid = models.ForeignKey(
        "bidding.Bid",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    pending_bid = models.ForeignKey(
        "bidding.Bid",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pending_on_boards",
    )
    current_controller = models.ForeignKey(
        "accounts.UserProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="controlled_boards",
    )
    current_amount_cents = models.PositiveIntegerField(default=0)
    current_message = models.CharField(
        max_length=80,
        blank=True,
        default=settings.TAKEBOARD_DEFAULT_BOARD_MESSAGE,
    )
    guaranteed_until = models.DateTimeField(null=True, blank=True)
    version = models.PositiveBigIntegerField(default=0)
    bidding_enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["-current_amount_cents"]),
            models.Index(fields=["bidding_enabled"]),
            models.Index(fields=["guaranteed_until"]),
        ]

    def __str__(self) -> str:
        return f"{self.school} board"

    @property
    def current_amount_dollars(self) -> Decimal:
        return Decimal(self.current_amount_cents) / 100


class BoardTakeover(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="takeovers")
    bid = models.OneToOneField("bidding.Bid", on_delete=models.PROTECT, related_name="takeover")
    previous_bid = models.ForeignKey(
        "bidding.Bid",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    controller = models.ForeignKey("accounts.UserProfile", on_delete=models.PROTECT)
    controller_display_name = models.CharField(max_length=40, default="", editable=False)
    represented_school = models.ForeignKey("schools.School", on_delete=models.PROTECT)
    season_week = models.ForeignKey(
        "leaderboard.SeasonWeek",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="takeovers",
    )
    message = models.CharField(max_length=80)
    amount_cents = models.PositiveIntegerField()
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["board", "-occurred_at"]),
            models.Index(fields=["represented_school", "-occurred_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.controller} took {self.board} for {self.amount_cents} cents"

    @property
    def amount_dollars(self) -> Decimal:
        return Decimal(self.amount_cents) / 100
