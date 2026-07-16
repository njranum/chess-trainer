"""Thin wrapper: `python manage.py calibrate --sample=50 [--out=PATH]`."""

from pathlib import Path

from django.core.management.base import BaseCommand

from puzzles.models import Puzzle
from puzzles.pipeline.calibrate import build_calibration_html


class Command(BaseCommand):
    help = "Dump a random sample of surviving puzzles to a static HTML page."

    def add_arguments(self, parser):
        parser.add_argument("--sample", type=int, default=50)
        parser.add_argument("--out", default="calibration/sample.html")

    def handle(self, *args, **options):
        puzzles = list(Puzzle.objects.order_by("?")[:options["sample"]])
        page = build_calibration_html(puzzles)
        out = Path(options["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page)
        self.stdout.write(self.style.SUCCESS(
            f"calibrate: {len(puzzles)} puzzles → {out}"))
