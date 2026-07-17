"""
Serving order (Design.md §8): overdue by (due_at, -quality_score); when
clear, introduce new puzzles by quality with a daily cap so the run-zero
corpus doesn't firehose week one; soft-mix PUNISH and AVOID; buried puzzles
excluded throughout.
"""

from django.utils import timezone

from puzzles.constants import NEW_PUZZLES_PER_DAY
from puzzles.models import Puzzle
from training.models import Attempt


def next_puzzle(now=None):
    now = now or timezone.now()
    available = Puzzle.objects.exclude(buried_until__gt=now)

    overdue = (available.filter(due_at__lte=now)
               .order_by("due_at", "-quality_score").first())
    if overdue is not None:
        return overdue

    if new_puzzles_started_today(now) >= NEW_PUZZLES_PER_DAY:
        return None

    fresh = available.filter(due_at__isnull=True).order_by("-quality_score")
    return _soft_mix(fresh, now)


def due_count(now=None) -> int:
    now = now or timezone.now()
    return (Puzzle.objects.exclude(buried_until__gt=now)
            .filter(due_at__lte=now).count())


def new_puzzles_started_today(now) -> int:
    """Puzzles whose FIRST attempt happened today."""
    start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return (Puzzle.objects
            .filter(attempts__created_at__gte=start)
            .exclude(attempts__created_at__lt=start)
            .distinct().count())


def _soft_mix(fresh, now):
    """Prefer the type trained less today, but never at a big quality cost:
    the preferred type only wins within the top handful by quality."""
    top = list(fresh[:5])
    if not top:
        return None
    start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    today = Attempt.objects.filter(created_at__gte=start)
    trained = {
        "avoid": today.filter(puzzle__puzzle_type="avoid").count(),
        "punish": today.filter(puzzle__puzzle_type="punish").count(),
    }
    preferred = "punish" if trained["punish"] <= trained["avoid"] else "avoid"
    for puzzle in top:
        if puzzle.puzzle_type == preferred:
            return puzzle
    return top[0]
