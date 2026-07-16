"""Table-driven sweep tests (Design.md §4): AVOID and PUNISH detection, the
punished-adequately non-candidate, opponent moves never flagged, and both
colours. Games are built move-by-move; evals are scripted per position."""

import chess
import chess.pgn
import pytest

from puzzles.pipeline.engine import PositionEval
from puzzles.pipeline.sweep import (
    CandidateMoment,
    classify_phase,
    clock_bucket,
    sweep_game,
)
from puzzles.tests.fakes import FakeEngine


def scripted_game(sans: list[str], wps: list[float]) -> tuple[str, FakeEngine]:
    """PGN + engine scripted so position i (before ply i+1) evals to wps[i].

    wps has len(sans) + 1 entries and is USER-perspective throughout.
    """
    assert len(wps) == len(sans) + 1
    game = chess.pgn.Game()
    node = game
    board = chess.Board()
    evals = {board.epd(): PositionEval(wp=wps[0], mate_in=None)}
    for san, wp_after in zip(sans, wps[1:], strict=True):
        move = board.parse_san(san)
        board.push(move)
        node = node.add_variation(move)
        evals[board.epd()] = PositionEval(wp=wp_after, mate_in=None)
    return str(game), FakeEngine(evals=evals)


class TestCandidateDetection:
    def test_avoid_and_punish_flagged_white_user(self):
        # 2.Qh5?? drops 22 (AVOID). 2...Nc6?? hands 28 back; 3.Nf3 realises
        # only 5 of it (< half) — PUNISH, even though it is also a 23-drop.
        pgn, engine = scripted_game(
            ["e4", "e5", "Qh5", "Nc6", "Nf3"],
            [52, 53, 52, 30, 58, 35],
        )
        candidates = sweep_game(pgn, chess.WHITE, engine)
        assert [(c.ply, c.candidate_type) for c in candidates] == [
            (3, "avoid"), (5, "punish"),
        ]
        avoid = candidates[0]
        assert avoid.played_san == "Qh5"
        assert avoid.wp_before == 52 and avoid.wp_after_played == 30
        assert avoid.fen_before.split()[1] == "w"  # user to move in the puzzle

    def test_punished_adequately_is_no_candidate(self):
        # Opponent hands 25; user's reply keeps 20 of it (≥ half): nothing
        # to train, and the small residual drop (5) is under MISTAKE too.
        pgn, engine = scripted_game(
            ["e4", "e5", "Nf3", "Nc6", "Bc4"],
            [50, 50, 50, 75, 70, 70],
        )
        assert sweep_game(pgn, chess.WHITE, engine) == []

    def test_opponent_swings_never_flagged(self):
        # 1...e5?? hands 30 (opponent ply 2 — a swing, but never a candidate
        # itself); 2.Nf3 realises only 5 of it → the PUNISH miss is ply 3,
        # the user's decision, not ply 2, the opponent's.
        pgn, engine = scripted_game(
            ["e4", "e5", "Nf3", "Nc6"],
            [50, 50, 80, 55, 55],
        )
        candidates = sweep_game(pgn, chess.WHITE, engine)
        assert [(c.ply, c.candidate_type) for c in candidates] == [(3, "punish")]

    def test_black_user_perspective(self):
        # User is black; 2...f6?? drops 28. White's moves are never flagged.
        pgn, engine = scripted_game(
            ["e4", "e5", "Nf3", "f6"],
            [48, 47, 48, 48, 20],
        )
        candidates = sweep_game(pgn, chess.BLACK, engine)
        assert [(c.ply, c.candidate_type) for c in candidates] == [(4, "avoid")]
        assert candidates[0].fen_before.split()[1] == "b"

    def test_small_drop_is_no_candidate(self):
        pgn, engine = scripted_game(["e4", "e5"], [50, 45, 50])  # 5 < MISTAKE
        assert sweep_game(pgn, chess.WHITE, engine) == []

    def test_clocks_attached(self):
        pgn, engine = scripted_game(["e4", "e5", "Qh5"], [52, 52, 52, 30])
        candidates = sweep_game(pgn, chess.WHITE, engine, clocks={3: 15.0})
        assert candidates[0].clock_seconds == 15.0
        no_clock = sweep_game(pgn, chess.WHITE, engine, clocks={})
        assert no_clock[0].clock_seconds is None

    def test_one_eval_per_position(self):
        pgn, engine = scripted_game(["e4", "e5", "Qh5"], [52, 52, 52, 30])
        sweep_game(pgn, chess.WHITE, engine)
        assert engine.eval_calls == 4  # positions = plies + 1; no re-evals


class TestPhase:
    def test_early_ply_is_opening(self):
        assert classify_phase(chess.Board(), ply=8) == "opening"

    def test_bare_rooks_is_endgame(self):
        board = chess.Board("4k3/8/8/8/8/8/8/R3K2R w KQ - 0 40")
        assert classify_phase(board, ply=79) == "endgame"

    def test_full_board_past_opening_is_middlegame(self):
        assert classify_phase(chess.Board(), ply=21) == "middlegame"


class TestClockBucket:
    @pytest.mark.parametrize("seconds,expected", [
        (None, ""), (300.0, "comfortable"), (61.0, "comfortable"),
        (60.0, "low"), (20.0, "low"), (19.9, "scramble"), (2.0, "scramble"),
    ])
    def test_buckets(self, seconds, expected):
        assert clock_bucket(seconds) == expected


def test_candidate_moment_is_plain_data():
    assert CandidateMoment.__dataclass_fields__  # regression guard: stays a dataclass
