"""Read pages owned by the puzzles app: the opening-leak table and the
filterable puzzle archive (Design.md §8)."""

from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import render

from .models import MotifTag, Occurrence, Puzzle


def openings_page(request):
    """Exact positions you keep reaching and keep misplaying, ranked by
    recurrence × cost."""
    leaks = []
    for puzzle in (Puzzle.objects.filter(is_opening_leak=True)
                   .prefetch_related("occurrences__game")):
        occurrences = list(puzzle.occurrences.all())
        games = {o.game for o in occurrences}
        sample = max(games, key=lambda g: g.end_time) if games else None
        avg_drop = (sum(puzzle.win_pct_before - o.win_pct_after_played
                        for o in occurrences) / len(occurrences)
                    if occurrences else 0.0)
        leaks.append({
            "puzzle": puzzle,
            "eco": sample.eco if sample else "",
            "opening_name": sample.opening_name if sample else "",
            "times_reached": len(games),
            "avg_drop": avg_drop,
            "rank": len(games) * avg_drop,
        })
    leaks.sort(key=lambda leak: -leak["rank"])
    return render(request, "puzzles/openings.html", {"leaks": leaks})


def archive_page(request):
    puzzles = (Puzzle.objects
               .annotate(games=Count("occurrences__game", distinct=True),
                         attempt_count=Count("attempts", distinct=True))
               .prefetch_related("motifs")
               .order_by("-quality_score"))
    filters = {}
    if request.GET.get("type") in ("avoid", "punish"):
        filters["puzzle_type"] = request.GET["type"]
    if request.GET.get("phase") in ("opening", "middlegame", "endgame"):
        filters["phase"] = request.GET["phase"]
    if request.GET.get("motif"):
        filters["motifs__slug"] = request.GET["motif"]
    if request.GET.get("clock"):
        puzzles = puzzles.filter(
            occurrences__clock_bucket=request.GET["clock"]).distinct()
    puzzles = puzzles.filter(**filters)

    page = Paginator(puzzles, 50).get_page(request.GET.get("page"))
    return render(request, "puzzles/archive.html", {
        "page": page,
        "motif_tags": MotifTag.objects.order_by("name"),
        "clock_buckets": Occurrence.ClockBucket.values,
        "current": {k: request.GET.get(k, "") for k in
                    ("type", "phase", "motif", "clock")},
    })
