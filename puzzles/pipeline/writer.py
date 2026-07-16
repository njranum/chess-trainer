"""
Gate 5 + persistence (Design.md §4 gate 5, §6): the Candidate ledger row for
every gate-evaluated moment, and Puzzle/Occurrence creation under the
collision policy for the ones that pass.

Collision policy (§6): identity is position_key alone; solutions freeze at
first analysis; a deeper (higher-movetime) re-analysis may overwrite engine
facts; occurrences always accumulate; PUNISH wins puzzle_type ties.
"""

import logging

import chess

from puzzles.constants import OPENING_LEAK_MIN_GAMES
from puzzles.models import Candidate, MotifTag, Occurrence, Puzzle, PuzzleMotif
from puzzles.pipeline.detectors import DetectionContext, classify_direction, detect_motifs
from puzzles.pipeline.gates import GateOutcome
from puzzles.pipeline.positions import position_key
from puzzles.pipeline.sweep import CandidateMoment, clock_bucket

logger = logging.getLogger(__name__)


def quality_score(max_drop_wp: float, uniqueness_gap_wp: float,
                  cashout_plies: int, occurrence_games: int) -> float:
    """Ranking, not gating (§4): swing × uniqueness × findability (faster
    cashout reads as more findable) × recurrence. Scale is arbitrary —
    only the ordering matters."""
    return round(
        (max_drop_wp / 100.0) * (uniqueness_gap_wp / 100.0)
        * occurrence_games / max(cashout_plies, 1),
        6,
    )


def book_promotable(game, key: str) -> bool:
    """Gate 4 override: this book position has now been reached (and
    misplayed) in enough distinct games, counting the current one."""
    prior_games = (Candidate.objects.filter(position_key=key)
                   .exclude(game=game).values("game").distinct().count())
    return prior_games + 1 >= OPENING_LEAK_MIN_GAMES


def persist_candidate(game, moment: CandidateMoment,
                      outcome: GateOutcome) -> Candidate:
    """Write the ledger row; on a pass, also create/join the Puzzle and its
    Occurrence. update_or_create throughout — re-analysis is safe."""
    key = position_key(moment.fen_before)
    candidate, _ = Candidate.objects.update_or_create(
        game=game, ply=moment.ply,
        defaults={
            "position_key": key,
            "fen": moment.fen_before,
            "candidate_type": moment.candidate_type,
            "played_uci": moment.played.uci(),
            "played_san": moment.played_san,
            "win_pct_before": moment.wp_before,
            "win_pct_after_played": moment.wp_after_played,
            "clock_seconds": moment.clock_seconds,
            "uniqueness_gap_wp": outcome.uniqueness_gap_wp,
            "shallow_depth_stable": outcome.shallow_depth_stable,
            "shallow_depth_used": outcome.shallow_depth_used,
            "cashout_plies": outcome.cashout_plies,
            "legal_move_count": outcome.legal_move_count,
            "verdict": (Candidate.Verdict.ACCEPTED if outcome.passed
                        else Candidate.Verdict.REJECTED),
            "rejection_gate": outcome.rejection_gate,
            "puzzle": None,
        },
    )
    if outcome.passed:
        puzzle = _persist_puzzle(game, moment, outcome, key,
                                 is_opening_leak=outcome.is_book)
        candidate.puzzle = puzzle
        candidate.save(update_fields=["puzzle"])
    return candidate


def _persist_puzzle(game, moment, outcome, key, *, is_opening_leak) -> Puzzle:
    engine_facts = {
        "fen": moment.fen_before,
        "win_pct_before": moment.wp_before,
        "solutions": outcome.solutions,
        "uniqueness_gap_wp": outcome.uniqueness_gap_wp,
        "shallow_depth_stable": outcome.shallow_depth_stable,
        "shallow_depth_used": outcome.shallow_depth_used,
        "cashout_plies": outcome.cashout_plies,
        "mate_in": outcome.mate_in,
        "engine_version": game.engine_version,
        "engine_movetime_ms": game.engine_movetime_ms,
    }
    puzzle = Puzzle.objects.filter(position_key=key).first()
    if puzzle is None:
        direction, tags = _classify(moment, outcome)
        puzzle = Puzzle.objects.create(
            position_key=key,
            puzzle_type=moment.candidate_type,
            direction=direction,
            phase=moment.phase,
            is_opening_leak=is_opening_leak,
            quality_score=0.0,  # set below once the occurrence exists
            **engine_facts,
        )
        _attach_motifs(puzzle, tags)
    else:
        changed = []
        # PUNISH wins the type on collision (§6) — log it, it's a decision.
        if (moment.candidate_type == Puzzle.PuzzleType.PUNISH
                and puzzle.puzzle_type != Puzzle.PuzzleType.PUNISH):
            logger.info("puzzle %s type collision: avoid → punish", puzzle.pk)
            puzzle.puzzle_type = Puzzle.PuzzleType.PUNISH
            changed.append("puzzle_type")
        # Deeper analysis may overwrite frozen engine facts.
        if (game.engine_movetime_ms or 0) > (puzzle.engine_movetime_ms or 0):
            direction, tags = _classify(moment, outcome)
            for field, value in engine_facts.items():
                setattr(puzzle, field, value)
            puzzle.direction = direction
            changed += [*engine_facts, "direction"]
            _attach_motifs(puzzle, tags)
        if is_opening_leak and not puzzle.is_opening_leak:
            puzzle.is_opening_leak = True
            changed.append("is_opening_leak")
        if changed:
            puzzle.save(update_fields=changed)

    _write_occurrence(puzzle, game, moment.ply, moment.played.uci(),
                      moment.played_san, moment.wp_after_played,
                      moment.clock_seconds)
    if is_opening_leak:
        _backfill_promoted_occurrences(puzzle, key, game)
    _refresh_quality(puzzle)
    return puzzle


def _classify(moment, outcome):
    board = chess.Board(moment.fen_before)
    solution = chess.Move.from_uci(outcome.solutions[0]["uci"])
    pv = [chess.Move.from_uci(u) for u in outcome.solutions[0]["pv_uci"]]
    ctx = DetectionContext(board=board, solution=solution, pv=pv,
                           played=moment.played,
                           puzzle_type=moment.candidate_type,
                           mate_in=outcome.mate_in)
    tags = detect_motifs(ctx)
    return classify_direction(ctx, tags), tags


def _attach_motifs(puzzle, tags: set[str]):
    for slug in tags:
        tag = MotifTag.objects.get(slug=slug)
        PuzzleMotif.objects.update_or_create(
            puzzle=puzzle, tag=tag,
            defaults={"source": PuzzleMotif.Source.RULE,
                      "confidence": 1.0, "rule_verified": True},
        )


def _write_occurrence(puzzle, game, ply, uci, san, wp_after, clock_seconds):
    Occurrence.objects.update_or_create(
        game=game, ply=ply,
        defaults={
            "puzzle": puzzle,
            "played_uci": uci,
            "played_san": san,
            "win_pct_after_played": wp_after,
            "clock_seconds": clock_seconds,
            "clock_bucket": clock_bucket(clock_seconds),
        },
    )


def _backfill_promoted_occurrences(puzzle, key: str, current_game):
    """Opening-leak promotion (§4 gate 4): the first N−1 occurrences were
    book-rejected before anyone knew the position recurs. Their Candidate
    rows carry everything an Occurrence needs — join them to the puzzle."""
    prior = (Candidate.objects.filter(position_key=key, puzzle__isnull=True)
             .exclude(game=current_game))
    for cand in prior:
        _write_occurrence(puzzle, cand.game, cand.ply, cand.played_uci,
                          cand.played_san, cand.win_pct_after_played,
                          cand.clock_seconds)
        cand.puzzle = puzzle
        cand.verdict = Candidate.Verdict.ACCEPTED
        cand.rejection_gate = None
        cand.save(update_fields=["puzzle", "verdict", "rejection_gate"])


def _refresh_quality(puzzle):
    occurrences = list(puzzle.occurrences.all())
    max_drop = max(puzzle.win_pct_before - o.win_pct_after_played
                   for o in occurrences)
    games = len({o.game_id for o in occurrences})
    puzzle.quality_score = quality_score(
        max_drop, puzzle.uniqueness_gap_wp, puzzle.cashout_plies, games
    )
    puzzle.save(update_fields=["quality_score"])
