from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import SchoolWeekStats, SeasonWeek


@admin.register(SeasonWeek)
class SeasonWeekAdmin(ModelAdmin):
    list_display = (
        "year",
        "week_number",
        "starts_at",
        "ends_at",
        "active",
        "reset_completed_at",
    )
    list_filter = ("active", "year")
    ordering = ("-starts_at",)
    readonly_fields = ("reset_completed_at",)


@admin.register(SchoolWeekStats)
class SchoolWeekStatsAdmin(ModelAdmin):
    list_display = (
        "school",
        "week",
        "total_spend_cents",
        "takeovers",
        "boards_attacked",
        "biggest_bid_cents",
    )
    list_filter = ("week", "school")
    search_fields = ("school__name",)
