"""Pipeline-health page (Design.md §7–§8): ingest/analysis status per game
plus PipelineRun history — where silence goes to be seen."""

from django.db.models import Count
from django.shortcuts import render

from .models import Game, PipelineRun


def health_page(request):
    status_counts = dict(
        Game.objects.values_list("analysis_status")
        .annotate(n=Count("id"))
        .values_list("analysis_status", "n")
    )
    return render(request, "games/health.html", {
        "status_counts": status_counts,
        "total_games": Game.objects.count(),
        "runs": PipelineRun.objects.order_by("-started_at")[:25],
        "failed_games": Game.objects.filter(
            analysis_status=Game.AnalysisStatus.FAILED)[:20],
    })
