"""
Tier-1 motif detectors + direction classification (Design.md §5).

Pure functions over a DetectionContext: (puzzle position, solution, PV,
played move) → mechanism tags describing what the SOLUTION exploits, plus
exactly one direction describing how the user related to it.

These are deliberately bounded heuristics, not oracles: each detector's
contract is its fixture tests; the fuzzy remainder belongs to Tier 2 (LLM)
and OTHER. False negatives are acceptable, confident false positives are
not — thresholds lean conservative.
"""

from dataclasses import dataclass, field

import chess

from puzzles.pipeline.material import PIECE_VALUES
from puzzles.pipeline.see import best_capture_gain, see

SLIDERS = (chess.BISHOP, chess.ROOK, chess.QUEEN)


@dataclass
class DetectionContext:
    board: chess.Board            # the puzzle position — user to move
    solution: chess.Move          # primary solution (engine best)
    pv: list[chess.Move] = field(default_factory=list)
    played: chess.Move | None = None
    puzzle_type: str = "avoid"    # "avoid" | "punish"
    mate_in: int | None = None

    def __post_init__(self):
        self.user = self.board.turn
        self.enemy = not self.user
        self.after = self.board.copy()
        self.after.push(self.solution)


# --- Group A: SEE-based (M3-07) ---------------------------------------------

def detect_hanging_piece(ctx: DetectionContext) -> bool:
    """The solution simply wins material by capturing: SEE > 0."""
    return ctx.board.is_capture(ctx.solution) and see(ctx.board, ctx.solution) > 0


def detect_counting_error(ctx: DetectionContext) -> bool:
    """The PLAYED move started a capture sequence that resolves negatively —
    the user miscounted an exchange."""
    if ctx.played is None or not ctx.board.is_capture(ctx.played):
        return False
    return see(ctx.board, ctx.played) < 0


# --- Group B: ray logic (M3-08) ----------------------------------------------

def detect_fork(ctx: DetectionContext) -> bool:
    """After the solution, the moved piece attacks ≥ 2 profitable targets
    (king counts; otherwise higher value than the attacker, or undefended)."""
    attacker_sq = ctx.solution.to_square
    attacker = ctx.after.piece_at(attacker_sq)
    if attacker is None:
        return False
    attacker_value = PIECE_VALUES[attacker.piece_type]
    targets = 0
    for sq in ctx.after.attacks(attacker_sq):
        piece = ctx.after.piece_at(sq)
        if piece is None or piece.color != ctx.enemy:
            continue
        profitable = (
            piece.piece_type == chess.KING
            or PIECE_VALUES[piece.piece_type] > attacker_value
            or not ctx.after.is_attacked_by(ctx.enemy, sq)  # undefended
        )
        if profitable:
            targets += 1
    return targets >= 2


def detect_pin(ctx: DetectionContext) -> bool:
    """After the solution, an enemy piece is absolutely pinned AND attacked
    by the user — the pin is doing tactical work, not just existing."""
    for sq, piece in ctx.after.piece_map().items():
        if piece.color != ctx.enemy or piece.piece_type == chess.KING:
            continue
        if ctx.after.is_pinned(ctx.enemy, sq) and ctx.after.is_attacked_by(ctx.user, sq):
            return True
    return False


def detect_skewer(ctx: DetectionContext) -> bool:
    """The solution is a slider move whose ray hits a valuable enemy piece
    with a lesser enemy piece behind it on the same ray (front > back)."""
    piece = ctx.after.piece_at(ctx.solution.to_square)
    if piece is None or piece.piece_type not in SLIDERS:
        return False
    attacker_value = PIECE_VALUES[piece.piece_type]
    for front_sq in ctx.after.attacks(ctx.solution.to_square):
        front = ctx.after.piece_at(front_sq)
        if front is None or front.color != ctx.enemy:
            continue
        front_value = PIECE_VALUES[front.piece_type]
        forced = front.piece_type == chess.KING or front_value > attacker_value
        if not forced:
            continue
        back = _piece_behind(ctx.after, ctx.solution.to_square, front_sq)
        if back is None:
            continue
        back_sq, back_piece = back
        if back_piece.color == ctx.enemy and back_piece.piece_type != chess.KING:
            back_value = PIECE_VALUES[back_piece.piece_type]
            if front_value > back_value or front.piece_type == chess.KING:
                return True
    return False


def detect_discovered_attack(ctx: DetectionContext) -> bool:
    """Moving the solution piece unmasks a user slider's attack on a valuable
    enemy piece (≥ minor) or the king."""
    vacated = ctx.solution.from_square
    for sq, piece in ctx.board.piece_map().items():
        if piece.color != ctx.user or piece.piece_type not in SLIDERS:
            continue
        if sq == vacated:
            continue
        newly_attacked = (ctx.after.attacks(sq) & ~ctx.board.attacks(sq))
        for target_sq in newly_attacked:
            target = ctx.after.piece_at(target_sq)
            if (target is not None and target.color == ctx.enemy
                    and (target.piece_type == chess.KING
                         or PIECE_VALUES[target.piece_type] >= 3)
                    and vacated in chess.SquareSet.between(sq, target_sq)):
                return True
    return False


def _piece_behind(board, attacker_sq, front_sq):
    """First piece on the attacker→front ray, strictly beyond front."""
    beyond = [s for s in chess.SquareSet.ray(attacker_sq, front_sq)
              if front_sq in chess.SquareSet.between(attacker_sq, s)]
    for sq in sorted(beyond, key=lambda s: chess.square_distance(front_sq, s)):
        piece = board.piece_at(sq)
        if piece is not None:
            return sq, piece
    return None


# --- Group C: pattern + PV based (M3-09) --------------------------------------

def detect_back_rank(ctx: DetectionContext) -> bool:
    """The PV ends in checkmate delivered by a rook/queen on the enemy back
    rank, with the enemy king on that rank."""
    final = ctx.board.copy()
    for move in ctx.pv:
        final.push(move)
    if not final.is_checkmate():
        return False
    king_sq = final.king(ctx.enemy)
    back_rank = 7 if ctx.enemy == chess.BLACK else 0
    if chess.square_rank(king_sq) != back_rank:
        return False
    for checker_sq in final.checkers():
        piece = final.piece_at(checker_sq)
        if (piece.piece_type in (chess.ROOK, chess.QUEEN)
                and chess.square_rank(checker_sq) == back_rank):
            return True
    return False


def detect_trapped_piece(ctx: DetectionContext) -> bool:
    """After the solution, some enemy piece (minor or better) is attacked,
    cannot profitably stay, and every flight square loses it too."""
    for sq, piece in ctx.after.piece_map().items():
        if piece.color != ctx.enemy or piece.piece_type in (chess.KING, chess.PAWN):
            continue
        if not ctx.after.is_attacked_by(ctx.user, sq):
            continue
        if _capture_now_gain(ctx.after, sq) <= 0:
            continue  # staying doesn't actually lose it
        escapes = [m for m in ctx.after.legal_moves if m.from_square == sq]
        if not escapes:
            return True
        if all(_escape_still_loses(ctx.after, m) for m in escapes):
            return True
    return False


def _capture_now_gain(board_after: chess.Board, sq: chess.Square) -> int:
    """User's best SEE capturing at sq, evaluated via a null move (it is the
    enemy's turn in board_after)."""
    if board_after.is_check():
        return 0  # null move would be illegal; be conservative
    probe = board_after.copy()
    probe.push(chess.Move.null())
    return best_capture_gain(probe, sq)


def _escape_still_loses(board_after: chess.Board, escape: chess.Move) -> bool:
    probe = board_after.copy()
    probe.push(escape)
    return best_capture_gain(probe, escape.to_square) > 0


def detect_mate_threat(ctx: DetectionContext) -> bool:
    """The solution leads to forced mate."""
    return ctx.mate_in is not None


def detect_promotion(ctx: DetectionContext) -> bool:
    """The solution promotes, the PV contains a user promotion, or the
    solution pushes a passed pawn to the 6th rank or beyond."""
    if ctx.solution.promotion:
        return True
    for i, move in enumerate(ctx.pv):
        if i % 2 == 0 and move.promotion:  # user's moves are even PV indices
            return True
    piece = ctx.board.piece_at(ctx.solution.from_square)
    if piece is not None and piece.piece_type == chess.PAWN:
        rank = chess.square_rank(ctx.solution.to_square)
        advanced = rank >= 5 if ctx.user == chess.WHITE else rank <= 2
        return advanced and _is_passed_pawn(ctx.after, ctx.solution.to_square, ctx.user)
    return False


def _is_passed_pawn(board: chess.Board, sq: chess.Square, color: chess.Color) -> bool:
    file, rank = chess.square_file(sq), chess.square_rank(sq)
    ahead = range(rank + 1, 8) if color == chess.WHITE else range(rank - 1, -1, -1)
    for r in ahead:
        for f in (file - 1, file, file + 1):
            if 0 <= f <= 7:
                piece = board.piece_at(chess.square(f, r))
                if (piece is not None and piece.color != color
                        and piece.piece_type == chess.PAWN):
                    return False
    return True


DETECTORS = {
    "hanging-piece": detect_hanging_piece,
    "counting-error": detect_counting_error,
    "fork": detect_fork,
    "pin": detect_pin,
    "skewer": detect_skewer,
    "discovered-attack": detect_discovered_attack,
    "back-rank": detect_back_rank,
    "trapped-piece": detect_trapped_piece,
    "mate-threat": detect_mate_threat,
    "promotion": detect_promotion,
}


def detect_motifs(ctx: DetectionContext) -> set[str]:
    return {slug for slug, fn in DETECTORS.items() if fn(ctx)}


def classify_direction(ctx: DetectionContext, tags: set[str]) -> str:
    """Exactly one direction (Design.md §5):
    MISCOUNTED — the played capture sequence came out negative;
    MISSED     — a tactic for the user existed (all PUNISH puzzles, and AVOID
                 puzzles whose solution itself wins material or mates);
    ALLOWED    — the user's move enabled the tactic against them (default)."""
    if "counting-error" in tags:
        return "miscounted"
    if ctx.puzzle_type == "punish" or ctx.mate_in is not None:
        return "missed"
    if ctx.board.is_capture(ctx.solution) and see(ctx.board, ctx.solution) > 0:
        return "missed"
    return "allowed"
