"""
Stockfish session for the two-phase analyze pass (Design.md §7).

Phase 1 uses eval_position (single PV, movetime) over every ply; phase 2
uses top_moves (MultiPV) + best_at_depth (shallow findability probe) only at
candidate moments. All win% leaving this module are already user-perspective
via evals.score_to_user_wp — raw engine scores never escape.

Movetime, not fixed depth, for predictable runtime on the shared box.
"""

from dataclasses import dataclass, field

import chess
import chess.engine

from puzzles.constants import MULTIPV, SHALLOW_DEPTH
from puzzles.pipeline.evals import score_to_user_wp


@dataclass
class PositionEval:
    """User-perspective evaluation of one position."""

    wp: float                    # win% for the user, best play assumed
    mate_in: int | None          # +N = user mates in N moves; None otherwise
    pv: list[chess.Move] = field(default_factory=list)

    @classmethod
    def from_info(cls, info: dict, pov: chess.Color) -> "PositionEval":
        score = info["score"]
        pov_score = score.pov(pov)
        mate = pov_score.mate()
        return cls(
            wp=score_to_user_wp(score, pov),
            mate_in=mate if mate is not None and mate > 0 else None,
            pv=list(info.get("pv", [])),
        )


@dataclass
class MoveEval:
    """One MultiPV entry: a root move and the eval if it is played."""

    move: chess.Move
    wp: float                    # user-perspective, after this move, best play
    mate_in: int | None
    pv: list[chess.Move] = field(default_factory=list)


class StockfishSession:
    """One engine process reused across a whole analyze run."""

    def __init__(self, path: str, movetime_ms: int):
        if not path:
            raise ValueError("STOCKFISH_PATH is not set")
        self.movetime_ms = movetime_ms
        self._engine = chess.engine.SimpleEngine.popen_uci(path)
        self.name = self._engine.id.get("name", "unknown engine")

    def eval_position(self, board: chess.Board, pov: chess.Color) -> PositionEval:
        """Phase-1 sweep eval: single PV at movetime."""
        info = self._engine.analyse(
            board, chess.engine.Limit(time=self.movetime_ms / 1000)
        )
        return PositionEval.from_info(info, pov)

    def top_moves(self, board: chess.Board, pov: chess.Color,
                  multipv: int = MULTIPV) -> list[MoveEval]:
        """Phase-2 candidate probe: top N root moves, best first."""
        infos = self._engine.analyse(
            board, chess.engine.Limit(time=self.movetime_ms / 1000), multipv=multipv
        )
        moves = []
        for info in infos:
            if "pv" not in info or not info["pv"]:
                continue
            pos_eval = PositionEval.from_info(info, pov)
            moves.append(MoveEval(move=info["pv"][0], wp=pos_eval.wp,
                                  mate_in=pos_eval.mate_in, pv=pos_eval.pv))
        return moves

    def best_at_depth(self, board: chess.Board, depth: int = SHALLOW_DEPTH) -> chess.Move:
        """Gate-2 findability probe: the engine's first instinct."""
        info = self._engine.analyse(board, chess.engine.Limit(depth=depth))
        return info["pv"][0]

    def close(self):
        self._engine.quit()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
