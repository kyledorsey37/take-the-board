from django.db import models


class Rivalry(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    school_a = models.ForeignKey(
        "schools.School",
        related_name="rivalries_a",
        on_delete=models.CASCADE,
    )
    school_b = models.ForeignKey(
        "schools.School",
        related_name="rivalries_b",
        on_delete=models.CASCADE,
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "rivalries"
        constraints = [
            models.UniqueConstraint(fields=["school_a", "school_b"], name="unique_rivalry_pair"),
        ]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["active", "name"]),
        ]

    def __str__(self) -> str:
        return self.name
