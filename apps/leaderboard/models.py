from django.db import models


class CompetitionPeriod(models.Model):
    competition = models.ForeignKey("schools.Competition", on_delete=models.PROTECT, related_name="periods")
    year = models.IntegerField()
    week_number = models.IntegerField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    active = models.BooleanField(default=False)
    reset_completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["competition", "year", "week_number"], name="unique_competition_period"),
        ]
        indexes = [
            models.Index(fields=["active", "-starts_at"]),
            models.Index(fields=["competition", "year", "week_number"]),
        ]

    def __str__(self) -> str:
        return f"{self.year} Week {self.week_number}"


class EntityPeriodStats(models.Model):
    entity = models.ForeignKey("schools.Entity", on_delete=models.CASCADE)
    period = models.ForeignKey(CompetitionPeriod, on_delete=models.CASCADE)
    total_spend_cents = models.BigIntegerField(default=0)
    takeovers = models.PositiveIntegerField(default=0)
    boards_attacked = models.PositiveIntegerField(default=0)
    biggest_bid_cents = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["entity", "period"], name="unique_entity_period"),
        ]
        indexes = [
            models.Index(fields=["entity", "period"]),
            models.Index(fields=["period", "-total_spend_cents"]),
        ]

    def __str__(self) -> str:
        return f"{self.entity} stats for {self.period}"
