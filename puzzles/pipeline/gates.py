"""
The five puzzle-quality gates (Design.md §4).

Pure with respect to the database: facts in (a CandidateMoment + engine),
verdict + evidence out. The caller (analyze) owns Candidate persistence and
the opening-leak promotion query — gate 4's book exclusion is overridden by
passing book_promotable=True.

Evaluation order is cost-ordered (cheap checks before engine probes);
rejection_gate always reports the DESIGN's gate number. Book rejections
therefore carry no probe evidence — the probes were never paid for.
"""

from dataclasses import dataclass, field

import chess

from puzzles.constants import (
    BOOK_PLY_CUTOFF,
    CASHOUT_MAX_PLIES,
    MATE_MAX_MOVES,
    MAX_SOLUTIONS,
    MULTIPV,
    SALVAGEABLE_WP_MIN,
    SHALLOW_DEPTH,
    SOLUTION_BAND_WP,
    TRIVIAL_MAX_LEGAL_MOVES,
    UNIQUENESS_GAP_WP,
)
from puzzles.pipeline.sweep import CandidateMoment

PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
                chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}

# How much of each solution's PV to persist: enough for serving (≤ 3 user
# moves ⇒ ≤ 6 plies) plus context either side.
PV_STORE_PLIES = CASHOUT_MAX_PLIES + 4


@dataclass
class GateOutcome:
    passed: bool
    rejection_gate: int | None = None
    is_book: bool = False
    # Evidence — populated as far as evaluation got (Candidate ledger fields)
    legal_move_count: int | None = None
    uniqueness_gap_wp: float | None = None
    shallow_depth_stable: bool | None = None
    shallow_depth_used: int | None = None
    cashout_plies: int | None = None
    mate_in: int | None = None
    solutions: list[dict] = field(default_factory=list)


def run_gates(moment: CandidateMoment, engine, *,
              book_promotable: bool = False) -> GateOutcome:
    board = chess.Board(moment.fen_before)
    user_color = board.turn  # the puzzle position is always the user to move
    outcome = GateOutcome(passed=False, is_book=moment.ply < BOOK_PLY_CUTOFF)

    # Gate 1 — it mattered. (Rejected moments still count in stats, via the
    # Candidate row the caller writes either way.)
    if moment.wp_before < SALVAGEABLE_WP_MIN:
        outcome.rejection_gate = 1
        return outcome

    # Gate 4 (cheap half) — trivial, forced recapture, book. Checked before
    # the probes so rejected book moments cost no engine time.
    outcome.legal_move_count = board.legal_moves.count()
    if outcome.legal_move_count <= TRIVIAL_MAX_LEGAL_MOVES:
        outcome.rejection_gate = 4
        return outcome
    sweep_best = moment.position_eval.pv[0] if moment.position_eval.pv else None
    if (moment.last_capture_square is not None and sweep_best is not None
            and sweep_best.to_square == moment.last_capture_square
            and board.is_capture(sweep_best)):
        outcome.rejection_gate = 4  # forced recapture — not a decision
        return outcome
    if outcome.is_book and not book_promotable:
        outcome.rejection_gate = 4  # book territory; recurrence may promote
        return outcome

    # Gate 3 — the solution is reasonably unique (MultiPV probe).
    tops = engine.top_moves(board, user_color, MULTIPV)
    if not tops:
        outcome.rejection_gate = 3
        return outcome
    best = tops[0]
    in_band = [t for t in tops if best.wp - t.wp <= SOLUTION_BAND_WP]
    non_band = [t for t in tops if best.wp - t.wp > SOLUTION_BAND_WP]
    outcome.solutions = [_solution_json(board, t) for t in in_band]
    outcome.mate_in = best.mate_in
    if len(in_band) > MAX_SOLUTIONS:
        outcome.rejection_gate = 3
        return outcome
    if not non_band:
        # Every probed move is within the band — uniqueness unprovable.
        outcome.rejection_gate = 3
        return outcome
    outcome.uniqueness_gap_wp = best.wp - non_band[0].wp
    if outcome.uniqueness_gap_wp < UNIQUENESS_GAP_WP:
        outcome.rejection_gate = 3
        return outcome

    # Gate 2a — findable: a strong human's first instinct survives, proxied
    # by the engine's own shallow-depth first choice.
    outcome.shallow_depth_used = SHALLOW_DEPTH
    outcome.shallow_depth_stable = (
        engine.best_at_depth(board, SHALLOW_DEPTH) == best.move
    )
    if not outcome.shallow_depth_stable:
        outcome.rejection_gate = 2
        return outcome

    # Gate 2b — the point cashes out: mate within MATE_MAX_MOVES, or realised
    # material gain within CASHOUT_MAX_PLIES along the PV. Positional wins
    # that never cash out concretely are engine-only — not puzzles.
    if best.mate_in is not None:
        if best.mate_in > MATE_MAX_MOVES:
            outcome.rejection_gate = 2
            return outcome
        outcome.cashout_plies = 2 * best.mate_in - 1
    else:
        outcome.cashout_plies = _material_cashout(board, best.pv, user_color)
        if outcome.cashout_plies is None:
            outcome.rejection_gate = 2
            return outcome

    # Gate 5 (dedup + context) is the writer's job — DB territory.
    outcome.passed = True
    return outcome


def _material_cashout(board: chess.Board, pv: list[chess.Move],
                      user_color: chess.Color) -> int | None:
    """First PV ply (1-based) where the user's material balance improves,
    within CASHOUT_MAX_PLIES. None = the gain never materialises."""
    working = board.copy()
    start = _material_balance(working, user_color)
    for ply, move in enumerate(pv[:CASHOUT_MAX_PLIES], start=1):
        working.push(move)
        if _material_balance(working, user_color) - start >= 1:
            return ply
    return None


def _material_balance(board: chess.Board, user_color: chess.Color) -> int:
    balance = 0
    for piece in board.piece_map().values():
        value = PIECE_VALUES[piece.piece_type]
        balance += value if piece.color == user_color else -value
    return balance


def _solution_json(board: chess.Board, move_eval) -> dict:
    return {
        "uci": move_eval.move.uci(),
        "san": board.san(move_eval.move),
        "win_pct": round(move_eval.wp, 1),
        "pv_uci": [m.uci() for m in move_eval.pv[:PV_STORE_PLIES]],
    }
