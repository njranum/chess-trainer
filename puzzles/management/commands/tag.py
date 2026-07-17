"""Thin wrapper: `python manage.py tag [--max-batches=N]`.

Optional by construction — the app is complete without it (Design.md §2)."""

from django.core.management.base import BaseCommand

from games.pipeline.runs import pipeline_run
from puzzles.pipeline.llm import claude_headless
from puzzles.pipeline.tagging import run_tag_stage


class Command(BaseCommand):
    help = "LLM Tier-2 tagging + explanations for untagged puzzles (batched)."

    def add_arguments(self, parser):
        parser.add_argument("--max-batches", type=int, default=None,
                            help="stop after N LLM calls (cost guard)")

    def handle(self, *args, **options):
        with pipeline_run("tag") as run:
            run.counts = run_tag_stage(claude_headless,
                                       max_batches=options["max_batches"])
        self.stdout.write(self.style.SUCCESS(f"tag: {run.counts}"))
