from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import EntityPeriodStats, CompetitionPeriod


@admin.register(CompetitionPeriod)
class CompetitionPeriodAdmin(ModelAdmin):
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


@admin.register(EntityPeriodStats)
class EntityPeriodStatsAdmin(ModelAdmin):
    list_display = (
        "entity",
        "period",
        "total_spend_cents",
        "takeovers",
        "boards_attacked",
        "biggest_bid_cents",
    )
    list_filter = ("period", "entity")
    search_fields = ("entity__name",)
