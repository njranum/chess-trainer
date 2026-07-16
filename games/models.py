"""Game ingestion + pipeline bookkeeping (Design.md §6–7)."""

from django.db import models


class TimeClass(models.TextChoices):
    BULLET = "bullet"
    BLITZ = "blitz"
    RAPID = "rapid"
    DAILY = "daily"


class Game(models.Model):
    """One chess.com game, plus the engine-analysis bookkeeping for it."""

    # Identity / provenance
    chesscom_uuid = models.CharField(max_length=64, unique=True)
    url = models.URLField()
    pgn = models.TextField()
    end_time = models.DateTimeField(db_index=True)

    # Game facts
    time_class = models.CharField(max_length=10, choices=TimeClass.choices)
    time_control = models.CharField(max_length=20)          # e.g. "600+5"
    rated = models.BooleanField(default=True)
    user_color = models.CharField(max_length=5)             # "white"/"black"
    user_rating = models.PositiveIntegerField()
    opponent_username = models.CharField(max_length=50)     # shown in serving
    opponent_rating = models.PositiveIntegerField()
    result = models.CharField(max_length=10)                # "win"/"loss"/"draw"
    eco = models.CharField(max_length=3, blank=True)        # e.g. "C50"
    opening_name = models.CharField(max_length=120, blank=True)

    # Analysis bookkeeping — reproducibility matters when you re-tune constants
    class AnalysisStatus(models.TextChoices):
        PENDING = "pending"
        ANALYZED = "analyzed"
        FAILED = "failed"

    analysis_status = models.CharField(
        max_length=10, choices=AnalysisStatus.choices,
        default=AnalysisStatus.PENDING, db_index=True,
    )
    analysis_failures = models.PositiveSmallIntegerField(default=0)  # three-strikes
    analysis_error = models.TextField(blank=True)
    engine_version = models.CharField(max_length=40, blank=True)   # "stockfish 16.1"
    engine_movetime_ms = models.PositiveIntegerField(null=True, blank=True)
    pipeline_version = models.CharField(max_length=20, blank=True)  # extractor version
    ingested_at = models.DateTimeField(auto_now_add=True)
    analyzed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-end_time"]

    def __str__(self):
        return f"{self.end_time:%Y-%m-%d} vs {self.opponent_username} ({self.result})"


class PipelineRun(models.Model):
    """One row per stage per run — the pipeline-health page's data source."""

    class Status(models.TextChoices):
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"

    stage = models.CharField(max_length=20)   # "ingest"/"analyze"/"tag"/"snapshot"
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.RUNNING)
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    counts = models.JSONField(default=dict)   # e.g. {"games": 12, "puzzles": 31,
                                              #       "tag_skipped": 1}
    error_text = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.stage} {self.started_at:%Y-%m-%d %H:%M} ({self.status})"
