from django.db import models


DEFAULT_COMPETITION_SLUG = "college-football"


class Competition(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    sport = models.CharField(max_length=50)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Entity(models.Model):
    competition = models.ForeignKey(
        Competition,
        on_delete=models.PROTECT,
        related_name="entities",
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField()
    short_name = models.CharField(max_length=50)
    group_name = models.CharField(max_length=50, blank=True)
    accent_color = models.CharField(max_length=7)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["competition__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["competition", "slug"],
                name="unique_entity_slug_per_competition",
            ),
        ]
        indexes = [
            models.Index(fields=["competition", "slug"]),
            models.Index(fields=["competition", "active", "name"]),
        ]

    def __str__(self) -> str:
        return self.name
