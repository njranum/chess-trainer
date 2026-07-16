"""
Analyze stage orchestration (Design.md §7 stage 2).

The database is the queue: query PENDING games, process each in ONE
transaction (crash ⇒ N fully-analyzed games + the rest still PENDING),
mark ANALYZED with version fields. Failures go FAILED with the error
recorded; three strikes stays failed for inspection.
"""

import logging

import chess
from django.db import transaction
from django.utils import timezone

from games.models import Game
from games.pipeline.pgn import clocks_by_ply
from puzzles.constants import BOOK_PLY_CUTOFF
from puzzles.pipeline.gates import run_gates
from puzzles.pipeline.positions import position_key
from puzzles.pipeline.sweep import sweep_game
from puzzles.pipeline.writer import book_promotable, persist_candidate

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "1"
MAX_ANALYSIS_FAILURES = 3


def analyze_pending(engine, *, limit: int | None = None) -> dict:
    """Process the PENDING queue. Returns counts for the PipelineRun row."""
    counts = {"games": 0, "failed": 0, "candidates": 0, "puzzles": 0}
    queue = Game.objects.filter(
        analysis_status=Game.AnalysisStatus.PENDING).order_by("end_time")
    if limit:
        queue = queue[:limit]
    for game in queue:
        try:
            game_counts = analyze_game(game, engine)
        except Exception:
            logger.exception("analyze failed for game %s", game.chesscom_uuid)
            game.analysis_failures += 1
            game.analysis_error = _last_traceback()
            game.analysis_status = Game.AnalysisStatus.FAILED
            game.save(update_fields=["analysis_failures", "analysis_error",
                                     "analysis_status"])
            counts["failed"] += 1
            continue
        counts["games"] += 1
        counts["candidates"] += game_counts["candidates"]
        counts["puzzles"] += game_counts["puzzles"]
    return counts


def analyze_game(game: Game, engine) -> dict:
    """One game, one transaction — the resumability mechanism."""
    user_color = chess.WHITE if game.user_color == "white" else chess.BLACK
    with transaction.atomic():
        # Provenance first — the writer copies it onto every Puzzle it
        # creates and compares movetimes for the deeper-overwrite policy.
        game.engine_version = engine.name
        game.engine_movetime_ms = engine.movetime_ms
        game.pipeline_version = PIPELINE_VERSION

        moments = sweep_game(game.pgn, user_color, engine,
                             clocks=clocks_by_ply(game.pgn))
        puzzles = 0
        for moment in moments:
            promotable = False
            if moment.ply < BOOK_PLY_CUTOFF:
                promotable = book_promotable(game, position_key(moment.fen_before))
            outcome = run_gates(moment, engine, book_promotable=promotable)
            candidate = persist_candidate(game, moment, outcome)
            if candidate.puzzle_id is not None:
                puzzles += 1

        game.analysis_status = Game.AnalysisStatus.ANALYZED
        game.analysis_error = ""
        game.analyzed_at = timezone.now()
        game.save()
    return {"candidates": len(moments), "puzzles": puzzles}


def requeue_failed() -> int:
    """--retry-failed: FAILED games under the three-strikes limit go back to
    PENDING; three strikes stays failed for inspection."""
    return Game.objects.filter(
        analysis_status=Game.AnalysisStatus.FAILED,
        analysis_failures__lt=MAX_ANALYSIS_FAILURES,
    ).update(analysis_status=Game.AnalysisStatus.PENDING)


def requeue_analyzed(before_pipeline_version: str | None = None) -> int:
    """--reanalyze: reset ANALYZED games to PENDING. Re-analysis follows the
    §6 collision policy (deeper overwrites; occurrences accumulate)."""
    queue = Game.objects.filter(analysis_status=Game.AnalysisStatus.ANALYZED)
    if before_pipeline_version is not None:
        queue = queue.exclude(pipeline_version=before_pipeline_version)
    return queue.update(analysis_status=Game.AnalysisStatus.PENDING)


def _last_traceback() -> str:
    import traceback
    return traceback.format_exc()
