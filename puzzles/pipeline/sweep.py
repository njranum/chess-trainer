"""
Phase-1 sweep (Design.md §4, §7): one single-PV eval per position over the
whole game, then flag candidate moments.

Candidate producers:
- AVOID  — a user move whose played wp drop ≥ MISTAKE_WP_DROP.
- PUNISH — the opponent's previous move handed over ≥ BLUNDER_WP_DROP and
  the user's played reply realised < PUNISH_CAPTURE_FRACTION of it. A PUNISH
  moment is the same (game, ply) as its AVOID reading — PUNISH wins the type
  (rarer, more specific prompt; §6 collision policy).

All wp values are user-perspective (the engine wrapper guarantees it).
"""

import io
from dataclasses import dataclass

import chess
import chess.pgn

from puzzles.constants import (
    BLUNDER_WP_DROP,
    CLOCK_COMFORTABLE_MIN_S,
    CLOCK_SCRAMBLE_MAX_S,
    MISTAKE_WP_DROP,
    PHASE_ENDGAME_MAX_PIECES,
    PHASE_OPENING_MAX_PLY,
    PUNISH_CAPTURE_FRACTION,
)
from puzzles.pipeline.engine import PositionEval


@dataclass
class CandidateMoment:
    ply: int                    # 1-based half-move index of the USER's move
    fen_before: str             # position the user faced (the puzzle position)
    candidate_type: str         # "avoid" | "punish"
    played: chess.Move
    played_san: str
    wp_before: float            # user wp in fen_before (best play assumed)
    wp_after_played: float      # user wp after the user's actual move
    phase: str                  # "opening" | "middlegame" | "endgame"
    clock_seconds: float | None
    position_eval: PositionEval  # sweep eval of fen_before (pv reused by gates)
    last_capture_square: chess.Square | None = None  # opponent just captured
    #   here → gate 4's forced-recapture check


def sweep_game(pgn: str, user_color: chess.Color, engine,
               clocks: dict[int, float] | None = None) -> list[CandidateMoment]:
    """Replay the mainline, eval every position once, flag candidates."""
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None:
        return []

    boards: list[chess.Board] = [game.board()]
    moves: list[chess.Move] = []
    sans: list[str] = []
    board = game.board()
    for move in game.mainline_moves():
        sans.append(board.san(move))
        board.push(move)
        moves.append(move)
        boards.append(board.copy())

    # One eval per position: evals[i] is the position before ply i+1.
    evals = [engine.eval_position(b, user_color) for b in boards]

    clocks = clocks or {}
    candidates = []
    for i, move in enumerate(moves):
        ply = i + 1
        if boards[i].turn != user_color:
            continue  # only the user's decisions become puzzles

        wp_before, wp_after = evals[i].wp, evals[i + 1].wp
        drop = wp_before - wp_after

        candidate_type = None
        if i >= 1:
            handed = evals[i].wp - evals[i - 1].wp   # opponent's previous move
            realised = wp_after - evals[i - 1].wp
            if handed >= BLUNDER_WP_DROP and realised < PUNISH_CAPTURE_FRACTION * handed:
                candidate_type = "punish"
        if candidate_type is None and drop >= MISTAKE_WP_DROP:
            candidate_type = "avoid"
        if candidate_type is None:
            continue

        last_capture = None
        if i >= 1 and boards[i - 1].is_capture(moves[i - 1]):
            last_capture = moves[i - 1].to_square

        candidates.append(CandidateMoment(
            ply=ply,
            fen_before=boards[i].fen(),
            candidate_type=candidate_type,
            played=move,
            played_san=sans[i],
            wp_before=wp_before,
            wp_after_played=wp_after,
            phase=classify_phase(boards[i], ply),
            clock_seconds=clocks.get(ply),
            position_eval=evals[i],
            last_capture_square=last_capture,
        ))
    return candidates


def classify_phase(board: chess.Board, ply: int) -> str:
    """Simple, defensible phase rule: early plies are opening; few pieces
    left is endgame; otherwise middlegame."""
    if ply <= PHASE_OPENING_MAX_PLY:
        return "opening"
    non_pawn_pieces = sum(
        1 for square in chess.SQUARES
        if (piece := board.piece_at(square))
        and piece.piece_type not in (chess.PAWN, chess.KING)
    )
    if non_pawn_pieces <= PHASE_ENDGAME_MAX_PIECES:
        return "endgame"
    return "middlegame"


def clock_bucket(seconds: float | None) -> str:
    """"" (unknown) when the PGN had no %clk — absence is never fabricated."""
    if seconds is None:
        return ""
    if seconds > CLOCK_COMFORTABLE_MIN_S:
        return "comfortable"
    if seconds < CLOCK_SCRAMBLE_MAX_S:
        return "scramble"
    return "low"
