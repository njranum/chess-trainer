"""Engine wrapper tests. The perspective/mate plumbing is unit-tested via
PositionEval; the @engine tests need a real Stockfish (STOCKFISH_PATH)."""

import os

import chess
import chess.engine
import pytest
from chess.engine import Cp, Mate, PovScore

from puzzles.pipeline.engine import PositionEval, StockfishSession

STOCKFISH = os.environ.get("STOCKFISH_PATH", "")


class TestPositionEval:
    def test_pov_side_positive(self):
        info = {"score": PovScore(Cp(150), chess.WHITE), "pv": []}
        assert PositionEval.from_info(info, chess.WHITE).wp > 60

    def test_flip_for_black_user(self):
        info = {"score": PovScore(Cp(150), chess.WHITE), "pv": []}
        assert PositionEval.from_info(info, chess.BLACK).wp < 40

    def test_user_mating(self):
        info = {"score": PovScore(Mate(2), chess.WHITE), "pv": []}
        ev = PositionEval.from_info(info, chess.WHITE)
        assert ev.wp == 100.0 and ev.mate_in == 2

    def test_user_mated_has_no_mate_in(self):
        info = {"score": PovScore(Mate(2), chess.WHITE), "pv": []}
        ev = PositionEval.from_info(info, chess.BLACK)
        assert ev.wp == 0.0 and ev.mate_in is None


@pytest.mark.engine
@pytest.mark.skipif(not STOCKFISH, reason="STOCKFISH_PATH not set")
class TestRealEngine:
    def test_session_end_to_end(self):
        # Mate-in-one for white: back-rank with Re8#.
        board = chess.Board("6k1/5ppp/8/8/8/8/5PPP/4R1K1 w - - 0 1")
        board_mate = board.copy()
        board_mate.push_san("Re8")
        assert board_mate.is_checkmate()  # verify the position fact first

        with StockfishSession(STOCKFISH, movetime_ms=100) as engine:
            assert "stockfish" in engine.name.lower()

            ev = engine.eval_position(board, chess.WHITE)
            assert ev.wp == 100.0 and ev.mate_in == 1
            # Same position, black user: the flip in one assertion.
            assert engine.eval_position(board, chess.BLACK).wp == 0.0

            tops = engine.top_moves(board, chess.WHITE)
            assert tops[0].move == chess.Move.from_uci("e1e8")
            assert tops[0].wp == 100.0
            assert len(tops) >= 2 and tops[1].wp < 100.0

            assert engine.best_at_depth(board, depth=6) == chess.Move.from_uci("e1e8")
