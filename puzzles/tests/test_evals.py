"""Table-driven tests for the engine-boundary conversions (Design.md §3)."""

import chess
import chess.engine
import pytest
from chess.engine import Cp, Mate, MateGiven, PovScore

from puzzles.pipeline.evals import cp_to_wp, score_to_user_wp


class TestCpToWp:
    def test_equal_position_is_fifty(self):
        assert cp_to_wp(0) == 50.0

    @pytest.mark.parametrize("cp", [10, 50, 100, 150, 300, 800, 2000])
    def test_symmetry(self, cp):
        # +c for one side is exactly 100 − (win% of −c): zero-sum.
        assert cp_to_wp(cp) + cp_to_wp(-cp) == pytest.approx(100.0)

    def test_known_lichess_value(self):
        # +100 cp ≈ 59.1 wp under the Lichess constant.
        assert cp_to_wp(100) == pytest.approx(59.1, abs=0.1)

    def test_monotonic_and_compressive_at_extremes(self):
        # The whole reason for win% (§3): a 400 cp swing in a dead-lost
        # position moves win% far less than a 150 cp swing near equality.
        assert cp_to_wp(-1200) - cp_to_wp(-800) < 2.0
        assert cp_to_wp(150) - cp_to_wp(0) > 10.0
        wps = [cp_to_wp(c) for c in range(-2000, 2001, 50)]
        assert wps == sorted(wps)
        assert 0.0 <= wps[0] and wps[-1] <= 100.0


class TestScoreToUserWp:
    """The perspective flip — the classic silent-corruption bug (§3)."""

    @pytest.mark.parametrize("pov_color", [chess.WHITE, chess.BLACK])
    def test_user_is_pov_side(self, pov_color):
        score = PovScore(Cp(100), pov_color)
        assert score_to_user_wp(score, pov_color) == pytest.approx(cp_to_wp(100))

    @pytest.mark.parametrize("pov_color", [chess.WHITE, chess.BLACK])
    def test_user_is_other_side_flips(self, pov_color):
        score = PovScore(Cp(100), pov_color)
        assert score_to_user_wp(score, not pov_color) == pytest.approx(cp_to_wp(-100))

    def test_perspectives_sum_to_hundred(self):
        score = PovScore(Cp(237), chess.WHITE)
        total = score_to_user_wp(score, chess.WHITE) + score_to_user_wp(score, chess.BLACK)
        assert total == pytest.approx(100.0)

    def test_user_mating_clamps_to_hundred(self):
        assert score_to_user_wp(PovScore(Mate(3), chess.WHITE), chess.WHITE) == 100.0

    def test_user_getting_mated_clamps_to_zero(self):
        assert score_to_user_wp(PovScore(Mate(3), chess.WHITE), chess.BLACK) == 0.0
        assert score_to_user_wp(PovScore(Mate(-2), chess.WHITE), chess.WHITE) == 0.0

    def test_mate_delivered(self):
        assert score_to_user_wp(PovScore(MateGiven, chess.BLACK), chess.BLACK) == 100.0
        assert score_to_user_wp(PovScore(MateGiven, chess.BLACK), chess.WHITE) == 0.0

    def test_long_mate_still_clamps(self):
        # Mate-in-30 is still 100, never sigmoid-ed.
        assert score_to_user_wp(PovScore(Mate(30), chess.WHITE), chess.WHITE) == 100.0
