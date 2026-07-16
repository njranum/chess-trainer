from django.contrib import admin

from .models import Game, PipelineRun


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ["end_time", "opponent_username", "opponent_rating", "result",
                    "time_class", "analysis_status", "engine_movetime_ms"]
    list_filter = ["analysis_status", "time_class", "rated", "result"]
    search_fields = ["chesscom_uuid", "opponent_username", "eco", "opening_name"]
    date_hierarchy = "end_time"
    readonly_fields = ["ingested_at", "analyzed_at"]


@admin.register(PipelineRun)
class PipelineRunAdmin(admin.ModelAdmin):
    list_display = ["stage", "status", "started_at", "finished_at", "counts"]
    list_filter = ["stage", "status"]
    readonly_fields = ["started_at"]
