from django.contrib import admin

from .models import Attempt, Report


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ["puzzle", "correct", "grade", "hints_used", "latency_ms",
                    "failed_at_ply", "created_at"]
    list_filter = ["correct", "grade", "hints_used"]
    readonly_fields = ["created_at"]


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ["puzzle", "note", "created_at", "resolved_at"]
    list_filter = [("resolved_at", admin.EmptyFieldListFilter)]
    readonly_fields = ["created_at"]
