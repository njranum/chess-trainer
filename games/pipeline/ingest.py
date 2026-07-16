"""Ingest stage: chess.com archives → Game rows (Design.md §7 stage 1).

Idempotent by construction: update_or_create on the game UUID. New games
land PENDING; existing games are refreshed (harmless — finished games never
change) without touching analysis bookkeeping.
"""

from games.models import Game

from .chesscom import ChesscomClient
from .pgn import parse_game


def ingest_games(client: ChesscomClient, since: tuple[int, int] | None = None) -> dict:
    """Fetch and upsert. Returns counts for the PipelineRun row."""
    counts = {"months": 0, "seen": 0, "created": 0, "updated": 0, "skipped": 0}
    for year, month in client.months_to_fetch(since):
        counts["months"] += 1
        for game_json in client.month_games(year, month):
            counts["seen"] += 1
            fields = parse_game(game_json, client.username)
            if fields is None:  # variant game or missing PGN
                counts["skipped"] += 1
                continue
            uuid = fields.pop("chesscom_uuid")
            _, created = Game.objects.update_or_create(
                chesscom_uuid=uuid, defaults=fields
            )
            counts["created" if created else "updated"] += 1
    return counts
