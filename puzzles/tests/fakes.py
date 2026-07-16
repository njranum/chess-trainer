"""Scripted engine double — unit tests never call Stockfish (CLAUDE.md)."""

import chess

from puzzles.pipeline.engine import MoveEval, PositionEval


class FakeEngine:
    """Serves canned evals keyed by EPD (position sans counters).

    evals:      {epd: PositionEval}          — for eval_position
    tops:       {epd: [MoveEval, ...]}       — for top_moves (best first)
    shallow:    {epd: chess.Move}            — for best_at_depth; defaults to
                                               the top_moves best when absent
    All wp values are user-perspective by construction — the fake sits above
    the evals.py boundary, exactly like the real session.
    """

    name = "fake engine 1.0"
    movetime_ms = 100

    def __init__(self, evals=None, tops=None, shallow=None):
        self.evals: dict[str, PositionEval] = evals or {}
        self.tops: dict[str, list[MoveEval]] = tops or {}
        self.shallow: dict[str, chess.Move] = shallow or {}
        self.eval_calls = 0
        self.probe_calls = 0

    def eval_position(self, board, pov):
        self.eval_calls += 1
        return self.evals[board.epd()]

    def top_moves(self, board, pov, multipv=3):
        self.probe_calls += 1
        return self.tops[board.epd()][:multipv]

    def best_at_depth(self, board, depth=10):
        epd = board.epd()
        if epd in self.shallow:
            return self.shallow[epd]
        return self.tops[epd][0].move

    def close(self):
        pass
