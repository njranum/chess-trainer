"""Stateless line evaluation (Design.md §8): solution set on move one, PV
after, opponent replies from the matched solution's own PV, illegal input
rejected. Pure — no DB."""

import pytest

from training.lines import IllegalLine, evaluate_line, required_user_moves

# Position: after 1.e4 d5 (white to move). Two accepted solutions with their
# own PVs — exd5 (3-ply line) and e5 (1-ply).
FEN = "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2"
SOLUTIONS = [
    {"uci": "e4d5", "san": "exd5", "win_pct": 58.0,
     "pv_uci": ["e4d5", "d8d5", "b1c3"]},
    {"uci": "e4e5", "san": "e5", "win_pct": 55.0, "pv_uci": ["e4e5"]},
]


class TestFirstMove:
    def test_primary_solution_starts_the_line(self):
        verdict = evaluate_line(FEN, SOLUTIONS, 6, ["e4d5"])
        assert verdict.status == "continue"
        assert verdict.opponent_reply_uci == "d8d5"
        assert verdict.moves_log == [{"uci": "e4d5", "verdict": "solution"}]

    def test_second_solution_has_its_own_line(self):
        # H3 fix in action: solution #2 must not crash or borrow #1's PV.
        verdict = evaluate_line(FEN, SOLUTIONS, 6, ["e4e5"])
        assert verdict.status == "solved"  # its PV is 1 ply — done

    def test_wrong_first_move_fails_at_ply_one(self):
        verdict = evaluate_line(FEN, SOLUTIONS, 6, ["g1f3"])
        assert verdict.status == "failed"
        assert verdict.failed_at_ply == 1
        assert verdict.moves_log == [{"uci": "g1f3", "verdict": "wrong"}]


class TestLineWalk:
    def test_pv_move_continues_then_completes(self):
        verdict = evaluate_line(FEN, SOLUTIONS, 6, ["e4d5", "b1c3"])
        # 3-ply PV, cashout 6 → required = ceil(3/2) = 2 user moves: solved.
        assert verdict.status == "solved"
        assert verdict.moves_log[1] == {"uci": "b1c3", "verdict": "pv"}

    def test_off_pv_second_move_fails_with_position(self):
        verdict = evaluate_line(FEN, SOLUTIONS, 6, ["e4d5", "g1f3"])
        assert verdict.status == "failed"
        assert verdict.failed_at_ply == 2
        assert verdict.moves_log[1]["verdict"] == "wrong"

    def test_cashout_caps_the_required_moves(self):
        # cashout 1 → one user move suffices even with a long PV.
        verdict = evaluate_line(FEN, SOLUTIONS, 1, ["e4d5"])
        assert verdict.status == "solved"


class TestIllegalInput:
    def test_illegal_move_raises(self):
        with pytest.raises(IllegalLine):
            evaluate_line(FEN, SOLUTIONS, 6, ["e4e6"])  # pawn can't jump there

    def test_unparseable_move_raises(self):
        with pytest.raises(IllegalLine):
            evaluate_line(FEN, SOLUTIONS, 6, ["zz9x"])

    def test_empty_list_raises(self):
        with pytest.raises(IllegalLine):
            evaluate_line(FEN, SOLUTIONS, 6, [])

    def test_illegal_after_reply_raises(self):
        # Second user move must be legal in the position AFTER d8d5.
        with pytest.raises(IllegalLine):
            evaluate_line(FEN, SOLUTIONS, 6, ["e4d5", "e4d5"])


class TestRequiredUserMoves:
    @pytest.mark.parametrize("pv_len,cashout,expected", [
        (1, 1, 1),    # mate in one
        (3, 6, 2),    # 3-ply pv
        (10, 6, 3),   # long pv, capped by cashout 6 → 3
        (10, None, 3),  # no cashout: capped by MAX_USER_MOVES
        (2, 6, 1),    # user move + reply
    ])
    def test_table(self, pv_len, cashout, expected):
        assert required_user_moves(["x"] * pv_len, cashout) == expected
