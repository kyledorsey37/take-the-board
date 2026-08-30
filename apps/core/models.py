from django.db import models


class GameConfig(models.Model):
    minimum_bid_increment_cents = models.PositiveIntegerField(default=100)
    maximum_bid_cents = models.PositiveIntegerField(default=50000)
    guaranteed_display_seconds = models.PositiveIntegerField(default=30)
    message_max_length = models.PositiveIntegerField(default=80)
    message_validation_expiration_minutes = models.PositiveIntegerField(default=10)
    bidding_enabled = models.BooleanField(default=True)
    moderation_enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "game configuration"
        verbose_name_plural = "game configuration"

    def __str__(self) -> str:
        return "Game configuration"


class Activity(models.Model):
    type = models.CharField(max_length=50)
    user = models.ForeignKey(
        "accounts.UserProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    board = models.ForeignKey(
        "boards.Board",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "activity"
        indexes = [
            models.Index(fields=["type", "-created_at"]),
            models.Index(fields=["board", "-created_at"]),
        ]

    def __str__(self) -> str:
        return self.type


class BoardVisit(models.Model):
    """A private, per-player board-view counter used to tailor the home page."""

    profile = models.ForeignKey(
        "accounts.UserProfile",
        on_delete=models.CASCADE,
        related_name="board_visits",
    )
    board = models.ForeignKey(
        "boards.Board",
        on_delete=models.CASCADE,
        related_name="profile_visits",
    )
    visit_count = models.PositiveIntegerField(default=0)
    last_visited_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "board"],
                name="core_unique_profile_board_visit",
            ),
        ]
        indexes = [
            models.Index(fields=["profile", "-visit_count", "-last_visited_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.profile} visited {self.board}"
