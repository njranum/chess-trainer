"""Dashboard rollups (Design.md §6) — rebuildable caches only."""

from django.db import models

from puzzles.models import MotifTag


class WeaknessSnapshot(models.Model):
    """
    Nightly per-motif rollup so the dashboard can show trends over time
    without recomputing history. Everything here is derivable from
    Candidate/Occurrence/Attempt — this is a cache, and can be rebuilt from
    scratch (snapshot is delete-and-recompute).
    """

    date = models.DateField()
    tag = models.ForeignKey(MotifTag, on_delete=models.CASCADE)
    # From your GAMES (are you still making this mistake?)
    occurrences_in_window = models.PositiveIntegerField()   # e.g. trailing 30d
    games_in_window = models.PositiveIntegerField()
    # From your TRAINING (are you solving it when drilled?)
    attempts = models.PositiveIntegerField()
    correct = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["date", "tag"],
                                    name="unique_snapshot_per_date_tag"),
        ]

    def __str__(self):
        return f"{self.tag} @ {self.date}"
