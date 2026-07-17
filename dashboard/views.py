"""Dashboard (Design.md §8): due count, streak, the motif table with the
games-vs-training gap, and Chart.js trends over the snapshot history."""

from datetime import timedelta

from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from puzzles.constants import SNAPSHOT_WINDOW_DAYS
from puzzles.models import MotifTag, Occurrence
from training.models import Attempt
from training.serving import due_count

from .models import WeaknessSnapshot


def dashboard_page(request):
    now = timezone.now()
    window_start = now - timedelta(days=SNAPSHOT_WINDOW_DAYS)

    rows = []
    for tag in MotifTag.objects.all():
        occurrences = Occurrence.objects.filter(
            puzzle__motifs=tag, game__end_time__gte=window_start).count()
        attempts = Attempt.objects.filter(puzzle__motifs=tag,
                                          created_at__gte=window_start)
        attempt_count = attempts.count()
        correct = attempts.filter(correct=True).count()
        if occurrences == 0 and attempt_count == 0:
            continue
        rows.append({
            "tag": tag,
            "occurrences": occurrences,
            "attempts": attempt_count,
            "solve_rate": round(100 * correct / attempt_count) if attempt_count else None,
        })
    rows.sort(key=lambda r: -r["occurrences"])

    return render(request, "dashboard/dashboard.html", {
        "due_count": due_count(now),
        "streak": _streak(now),
        "attempts_today": Attempt.objects.filter(
            created_at__gte=now.astimezone().replace(
                hour=0, minute=0, second=0, microsecond=0)).count(),
        "motif_rows": rows,
        "window_days": SNAPSHOT_WINDOW_DAYS,
    })


def trends_json(request):
    """Chart data from the snapshot history: per-motif game-side occurrences
    (top 5 motifs) and the overall training solve rate, by snapshot date."""
    snapshots = WeaknessSnapshot.objects.select_related("tag").order_by("date")
    dates = sorted({str(s.date) for s in snapshots})

    totals = {}
    by_tag_date = {}
    solve_by_date = {}
    for snap in snapshots:
        totals[snap.tag.name] = totals.get(snap.tag.name, 0) + snap.occurrences_in_window
        by_tag_date[(snap.tag.name, str(snap.date))] = snap.occurrences_in_window
        attempted, correct = solve_by_date.get(str(snap.date), (0, 0))
        solve_by_date[str(snap.date)] = (attempted + snap.attempts,
                                         correct + snap.correct)

    top_tags = [name for name, _ in
                sorted(totals.items(), key=lambda kv: -kv[1])[:5]]
    occurrence_datasets = [
        {"label": name,
         "data": [by_tag_date.get((name, d), 0) for d in dates]}
        for name in top_tags
    ]
    solve_rate = [
        round(100 * c / a) if a else None
        for a, c in (solve_by_date.get(d, (0, 0)) for d in dates)
    ]
    return JsonResponse({"dates": dates,
                         "occurrences": occurrence_datasets,
                         "solve_rate": solve_rate})


def _streak(now) -> int:
    """Consecutive training days ending today (or yesterday, so an unplayed
    morning doesn't read as a broken streak)."""
    days_with_attempts = set(
        Attempt.objects.dates("created_at", "day", order="DESC")[:400])
    day = now.astimezone().date()
    if day not in days_with_attempts:
        day -= timedelta(days=1)
    streak = 0
    while day in days_with_attempts:
        streak += 1
        day -= timedelta(days=1)
    return streak
