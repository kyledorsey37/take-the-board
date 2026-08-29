from django.db import models


class SeasonWeek(models.Model):
    year = models.IntegerField()
    week_number = models.IntegerField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    active = models.BooleanField(default=False)
    reset_completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["year", "week_number"], name="unique_season_week"),
        ]
        indexes = [
            models.Index(fields=["active", "-starts_at"]),
            models.Index(fields=["year", "week_number"]),
        ]

    def __str__(self) -> str:
        return f"{self.year} Week {self.week_number}"


class SchoolWeekStats(models.Model):
    school = models.ForeignKey("schools.School", on_delete=models.CASCADE)
    week = models.ForeignKey(SeasonWeek, on_delete=models.CASCADE)
    total_spend_cents = models.BigIntegerField(default=0)
    takeovers = models.PositiveIntegerField(default=0)
    boards_attacked = models.PositiveIntegerField(default=0)
    biggest_bid_cents = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["school", "week"], name="unique_school_week"),
        ]
        indexes = [
            models.Index(fields=["school", "week"]),
            models.Index(fields=["week", "-total_spend_cents"]),
        ]

    def __str__(self) -> str:
        return f"{self.school} stats for {self.week}"
