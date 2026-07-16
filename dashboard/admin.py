from django.contrib import admin

from .models import WeaknessSnapshot


@admin.register(WeaknessSnapshot)
class WeaknessSnapshotAdmin(admin.ModelAdmin):
    list_display = ["date", "tag", "occurrences_in_window", "games_in_window",
                    "attempts", "correct"]
    list_filter = ["tag"]
    date_hierarchy = "date"
