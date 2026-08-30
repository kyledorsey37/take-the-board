from django.db import models
from django.core.exceptions import ValidationError


class Rivalry(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    entity_a = models.ForeignKey(
        "schools.Entity",
        related_name="rivalries_a",
        on_delete=models.CASCADE,
    )
    entity_b = models.ForeignKey(
        "schools.Entity",
        related_name="rivalries_b",
        on_delete=models.CASCADE,
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "rivalries"
        constraints = [
            models.UniqueConstraint(fields=["entity_a", "entity_b"], name="unique_rivalry_pair"),
        ]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["active", "name"]),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        super().clean()
        if self.entity_a_id and self.entity_b_id and self.entity_a.competition_id != self.entity_b.competition_id:
            raise ValidationError("A rivalry must pair entities from the same competition.")
