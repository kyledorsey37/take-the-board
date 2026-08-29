from django.db import models
from django.db.models.functions import Lower


class UserProfile(models.Model):
    # Cognito `sub` is a stable opaque identifier, not an RFC UUID contract.
    cognito_sub = models.CharField(max_length=128, unique=True)
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=40, unique=True, null=True, blank=True)
    favorite_school = models.ForeignKey(
        "schools.School",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="fans",
    )
    is_banned = models.BooleanField(default=False)
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
