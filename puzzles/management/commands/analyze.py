"""Thin wrapper: `python manage.py analyze [--retry-failed] [--movetime=MS]
[--reanalyze [--before-pipeline-version=X]] [--limit=N]`."""

from django.conf import settings
from django.core.management.base import BaseCommand

from games.pipeline.runs import pipeline_run
from puzzles.constants import ENGINE_MOVETIME_MS_DEFAULT
from puzzles.pipeline.analyze import (
    analyze_pending,
    requeue_analyzed,
    requeue_failed,
)
from puzzles.pipeline.engine import StockfishSession


class Command(BaseCommand):
    help = "Analyze PENDING games: engine pass → gates → puzzles (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--movetime", type=int, default=ENGINE_MOVETIME_MS_DEFAULT,
                            metavar="MS", help="engine movetime per position")
        parser.add_argument("--retry-failed", action="store_true",
                            help="re-queue FAILED games (under three strikes)")
        parser.add_argument("--reanalyze", action="store_true",
                            help="reset ANALYZED games to PENDING first")
        parser.add_argument("--before-pipeline-version", metavar="X",
                            help="with --reanalyze: only games not at version X")
        parser.add_argument("--limit", type=int, help="process at most N games")

    def handle(self, *args, **options):
        with pipeline_run("analyze") as run:
            counts = {}
            if options["retry_failed"]:
                counts["requeued_failed"] = requeue_failed()
            if options["reanalyze"]:
                counts["requeued_analyzed"] = requeue_analyzed(
                    options["before_pipeline_version"])
            with StockfishSession(settings.STOCKFISH_PATH,
                                  movetime_ms=options["movetime"]) as engine:
                counts |= analyze_pending(engine, limit=options["limit"])
            run.counts = counts
        self.stdout.write(self.style.SUCCESS(f"analyze: {run.counts}"))
