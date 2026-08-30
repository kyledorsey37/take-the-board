from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Rivalry


@admin.register(Rivalry)
class RivalryAdmin(ModelAdmin):
    list_display = ("name", "entity_a", "entity_b", "active")
    list_filter = ("active",)
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug", "entity_a__name", "entity_b__name")
