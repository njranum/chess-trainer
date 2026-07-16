from django.contrib import admin

from .models import Candidate, MotifTag, Occurrence, Puzzle, PuzzleMotif


@admin.register(MotifTag)
class MotifTagAdmin(admin.ModelAdmin):
    list_display = ["slug", "name", "tier"]
    list_filter = ["tier"]


class OccurrenceInline(admin.TabularInline):
    model = Occurrence
    extra = 0
    readonly_fields = ["game", "ply", "played_san", "win_pct_after_played",
                       "clock_seconds", "clock_bucket"]


class PuzzleMotifInline(admin.TabularInline):
    model = PuzzleMotif
    extra = 0


@admin.register(Puzzle)
class PuzzleAdmin(admin.ModelAdmin):
    list_display = ["id", "puzzle_type", "direction", "phase", "quality_score",
                    "is_opening_leak", "due_at", "tagged_at"]
    list_filter = ["puzzle_type", "direction", "phase", "is_opening_leak"]
    search_fields = ["fen", "position_key"]
    readonly_fields = ["created_at", "position_key"]
    inlines = [OccurrenceInline, PuzzleMotifInline]


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ["game", "ply", "candidate_type", "played_san", "verdict",
                    "rejection_gate", "puzzle"]
    list_filter = ["verdict", "candidate_type", "rejection_gate"]
    search_fields = ["position_key", "fen"]


@admin.register(Occurrence)
class OccurrenceAdmin(admin.ModelAdmin):
    list_display = ["puzzle", "game", "ply", "played_san", "clock_bucket"]
    list_filter = ["clock_bucket"]
