from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Rivalry


@admin.register(Rivalry)
class RivalryAdmin(ModelAdmin):
    list_display = ("name", "school_a", "school_b", "active")
    list_filter = ("active",)
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug", "school_a__name", "school_b__name")
