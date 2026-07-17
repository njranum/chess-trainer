"""Thin wrapper: `python manage.py snapshot` (nightly via cron)."""

from django.core.management.base import BaseCommand

from dashboard.pipeline.snapshot import take_snapshot
from games.pipeline.runs import pipeline_run


class Command(BaseCommand):
    help = "Delete-and-recompute today's WeaknessSnapshot rollups (idempotent)."

    def handle(self, *args, **options):
        with pipeline_run("snapshot") as run:
            run.counts = take_snapshot()
        self.stdout.write(self.style.SUCCESS(f"snapshot: {run.counts}"))
