"""Thin wrapper: `python manage.py ingest [--since=YYYY-MM]`."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from games.pipeline.chesscom import ChesscomClient
from games.pipeline.ingest import ingest_games
from games.pipeline.runs import pipeline_run


class Command(BaseCommand):
    help = "Upsert games from the chess.com archives API (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--since", metavar="YYYY-MM",
            help="Backfill: fetch every archive month from this one onward. "
                 "Without it, only the current + previous month are fetched.",
        )

    def handle(self, *args, **options):
        since = None
        if options["since"]:
            try:
                year, month = options["since"].split("-")
                since = (int(year), int(month))
            except ValueError as exc:
                raise CommandError("--since must be YYYY-MM") from exc

        client = ChesscomClient(settings.CHESSCOM_USERNAME)
        with pipeline_run("ingest") as run:
            run.counts = ingest_games(client, since=since)
        self.stdout.write(self.style.SUCCESS(f"ingest: {run.counts}"))
