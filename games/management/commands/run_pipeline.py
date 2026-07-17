"""Thin wrapper: `python manage.py run_pipeline` — ingest → analyze → tag.

Each stage is idempotent and writes its own PipelineRun row; a stage
failure stops the chain (the DB-as-queue means the next cron tick resumes
from reality)."""

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run the full pipeline: ingest → analyze → tag."

    def handle(self, *args, **options):
        for stage in ("ingest", "analyze", "tag"):
            call_command(stage)
