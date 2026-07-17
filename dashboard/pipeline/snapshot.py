"""
Snapshot stage (Design.md §7 stage 4): nightly delete-and-recompute of the
trailing-window per-motif rollups. A cache, rebuildable from scratch —
running twice for the same date is a no-op by construction.

Two distinct questions per motif (§6):
- games side  — are you still making this mistake? (occurrences whose game
  ended inside the window)
- training side — are you solving it when drilled? (attempts in the window)
The gap between them is the transfer question.
"""

from datetime import timedelta

from django.utils import timezone

from games.models import Game
from puzzles.constants import SNAPSHOT_WINDOW_DAYS
from puzzles.models import MotifTag, Occurrence
from training.models import Attempt

from ..models import WeaknessSnapshot


def take_snapshot(date=None) -> dict:
    """Recompute all per-motif rows for `date` (default today)."""
    now = timezone.now()
    date = date or now.date()
    window_start = now - timedelta(days=SNAPSHOT_WINDOW_DAYS)

    games_in_window = Game.objects.filter(end_time__gte=window_start).count()

    WeaknessSnapshot.objects.filter(date=date).delete()
    rows = []
    for tag in MotifTag.objects.all():
        occurrences = Occurrence.objects.filter(
            puzzle__motifs=tag, game__end_time__gte=window_start).count()
        attempts = Attempt.objects.filter(
            puzzle__motifs=tag, created_at__gte=window_start)
        attempt_count = attempts.count()
        correct = attempts.filter(correct=True).count()
        rows.append(WeaknessSnapshot(
            date=date, tag=tag, occurrences_in_window=occurrences,
            games_in_window=games_in_window, attempts=attempt_count,
            correct=correct,
        ))
    WeaknessSnapshot.objects.bulk_create(rows)
    return {"date": str(date), "tags": len(rows),
            "games_in_window": games_in_window}
