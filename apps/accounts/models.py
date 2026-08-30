from django.db import models
from django.db.models.functions import Lower


class UserProfile(models.Model):
    class RiskTier(models.TextChoices):
        NEW = "new", "New"
        ESTABLISHED = "established", "Established"
        TRUSTED = "trusted", "Trusted"
        RESTRICTED = "restricted", "Restricted"
        SUSPENDED = "suspended", "Suspended"

    # Cognito `sub` is a stable opaque identifier, not an RFC UUID contract.
    cognito_sub = models.CharField(max_length=128, unique=True)
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=40, unique=True, null=True, blank=True)
    favorite_entity = models.ForeignKey(
        "schools.Entity",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="fans",
    )
    is_banned = models.BooleanField(default=False)
    risk_tier = models.CharField(max_length=16, choices=RiskTier.choices, default=RiskTier.NEW)
    successful_bid_count = models.PositiveIntegerField(default=0)
    dispute_count = models.PositiveIntegerField(default=0)
    refund_count = models.PositiveIntegerField(default=0)
    last_dispute_at = models.DateTimeField(null=True, blank=True)
    has_open_dispute = models.BooleanField(default=False)
    paid_bidding_suspended = models.BooleanField(default=False)
    terms_version = models.CharField(max_length=50, blank=True)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    total_spend_cents = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["display_name"]),
            models.Index(fields=["cognito_sub"]),
        ]
        constraints = [
            models.UniqueConstraint(
                Lower("display_name"),
                name="accounts_unique_display_name_ci",
            ),
        ]

    def __str__(self) -> str:
        return self.display_name or self.email
