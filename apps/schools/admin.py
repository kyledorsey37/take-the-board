from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Competition, Entity


@admin.register(Competition)
class CompetitionAdmin(ModelAdmin):
    list_display = ("name", "sport", "slug", "active")
    list_filter = ("sport", "active")
    search_fields = ("name", "slug")


@admin.register(Entity)
class EntityAdmin(ModelAdmin):
    list_display = ("name", "competition", "short_name", "group_name", "accent_color", "active")
    list_filter = ("competition", "active", "group_name")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "short_name", "slug")
