from django.db import models


class School(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    short_name = models.CharField(max_length=50)
    conference = models.CharField(max_length=50, blank=True)
    accent_color = models.CharField(max_length=7)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["active", "name"]),
        ]

    def __str__(self) -> str:
        return self.name
