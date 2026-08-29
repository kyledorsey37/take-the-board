from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import School


@admin.register(School)
class SchoolAdmin(ModelAdmin):
    list_display = ("name", "short_name", "conference", "accent_color", "active")
    list_filter = ("active", "conference")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "short_name", "slug")
