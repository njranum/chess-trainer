"""Table-driven gate tests (Design.md §4): every gate's reject and pass
paths, evidence persistence, and the cheap-before-probes cost ordering.
Positions are constructed with python-chess and verified in the test before
being asserted on."""

import chess
import pytest

from puzzles.pipeline.engine import MoveEval, PositionEval
from puzzles.pipeline.gates import GateOutcome, run_gates
from puzzles.pipeline.sweep import CandidateMoment
from puzzles.tests.fakes import FakeEngine


def board_after(*sans):
    board = chess.Board()
    for san in sans:
        board.push_san(san)
    return board


def make_moment(board, ply=15, wp_before=55.0, wp_after=30.0,
                pv=None, last_capture=None) -> CandidateMoment:
    return CandidateMoment(
        ply=ply, fen_before=board.fen(), candidate_type="avoid",
        played=next(iter(board.legal_moves)), played_san="?",
        wp_before=wp_before, wp_after_played=wp_after, phase="middlegame",
        clock_seconds=None,
        position_eval=PositionEval(wp=wp_before, mate_in=None, pv=pv or []),
        last_capture_square=last_capture,
    )


def move_eval(board, san, wp, mate_in=None, pv_sans=()):
    """Build a MoveEval whose PV is verified legal from `board`."""
    working = board.copy()
    first = working.parse_san(san)
    pv = [first]
    working.push(first)
    for continuation in pv_sans:
        move = working.parse_san(continuation)
        pv.append(move)
        working.push(move)
    return MoveEval(move=first, wp=wp, mate_in=mate_in, pv=pv)


class TestGate1:
    def test_dead_lost_rejected_before_any_probe(self):
        engine = FakeEngine()
        outcome = run_gates(make_moment(chess.Board(), wp_before=20.0), engine)
        assert (outcome.passed, outcome.rejection_gate) == (False, 1)
        assert engine.probe_calls == 0


class TestGate4Cheap:
    def test_trivial_position_rejected(self):
        board = chess.Board("4R2k/6p1/8/8/8/8/8/K7 b - - 0 1")  # Re8+, Kh7 only
        assert 1 <= board.legal_moves.count() <= 2  # verify the position fact
        outcome = run_gates(make_moment(board, ply=40, wp_before=50.0), FakeEngine())
        assert outcome.rejection_gate == 4
        assert outcome.legal_move_count == board.legal_moves.count()

    def test_forced_recapture_rejected(self):
        # 1.e4 d5 2.exd5: black's obvious Qxd5 recapture is not a decision.
        board = board_after("e4", "d5", "exd5")
        recapture = board.parse_san("Qxd5")
        outcome = run_gates(
            make_moment(board, ply=24, wp_before=50.0, pv=[recapture],
                        last_capture=chess.D5),
            FakeEngine(),
        )
        assert outcome.rejection_gate == 4

    def test_book_rejected_without_paying_for_probes(self):
        engine = FakeEngine()
        board = board_after("e4", "e5", "Nf3", "Nc6")
        outcome = run_gates(make_moment(board, ply=5, wp_before=50.0), engine)
        assert outcome.rejection_gate == 4
        assert outcome.is_book is True
        assert engine.probe_calls == 0

    def test_book_promotable_proceeds_to_probes(self):
        board = board_after("e4", "e5", "Nf3", "Nc6")
        engine = FakeEngine(tops={board.epd(): [
            move_eval(board, "Bb5", 60.0, pv_sans=["a6", "Bxc6"]),
            move_eval(board, "d4", 45.0),
            move_eval(board, "Bc4", 42.0),
        ]})
        outcome = run_gates(make_moment(board, ply=5, wp_before=50.0), engine,
                            book_promotable=True)
        assert engine.probe_calls == 1  # the override paid for the probe
        assert outcome.rejection_gate != 4


class TestGate3:
    def test_too_many_solutions_rejected(self):
        board = board_after("e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5")
        engine = FakeEngine(tops={board.epd(): [
            move_eval(board, "c3", 55.0),
            move_eval(board, "d3", 53.0),     # in band (2)
            move_eval(board, "O-O", 51.0),    # in band (3) — too many
        ]})
        outcome = run_gates(make_moment(board, ply=11, wp_before=55.0), engine)
        assert outcome.rejection_gate == 3
        assert len(outcome.solutions) == 3  # evidence kept for the ledger

    def test_small_gap_rejected_with_evidence(self):
        board = board_after("e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5")
        engine = FakeEngine(tops={board.epd(): [
            move_eval(board, "c3", 60.0),
            move_eval(board, "d3", 52.0),     # gap 8: not in band, too close
            move_eval(board, "a3", 40.0),
        ]})
        outcome = run_gates(make_moment(board, ply=11, wp_before=60.0), engine)
        assert outcome.rejection_gate == 3
        assert outcome.uniqueness_gap_wp == pytest.approx(8.0)


class TestGate2:
    def board_and_tops(self, shallow_differs=False, quiet_pv=False):
        board = board_after("e4", "d5")  # white to move; exd5 wins a pawn
        if quiet_pv:
            best = move_eval(board, "Nf3", 58.0, pv_sans=["Nf6", "Nc3", "Nc6",
                                                          "d3", "e6"])
        else:
            best = move_eval(board, "exd5", 58.0, pv_sans=["Qxd5", "Nc3"])
        tops = {board.epd(): [
            best,
            move_eval(board, "Nc3", 45.0),
            move_eval(board, "d4", 44.0),
        ]}
        shallow = {}
        if shallow_differs:
            shallow[board.epd()] = board.parse_san("Nc3")
        return board, FakeEngine(tops=tops, shallow=shallow)

    def test_shallow_instability_rejected(self):
        board, engine = self.board_and_tops(shallow_differs=True)
        outcome = run_gates(make_moment(board, ply=12, wp_before=58.0), engine)
        assert outcome.rejection_gate == 2
        assert outcome.shallow_depth_stable is False
        assert outcome.shallow_depth_used == 10

    def test_quiet_pv_never_cashes_out_rejected(self):
        board, engine = self.board_and_tops(quiet_pv=True)
        outcome = run_gates(make_moment(board, ply=12, wp_before=58.0), engine)
        assert outcome.rejection_gate == 2
        assert outcome.cashout_plies is None

    def test_capture_cashes_out_at_ply_one(self):
        board, engine = self.board_and_tops()
        outcome = run_gates(make_moment(board, ply=12, wp_before=58.0), engine)
        assert outcome.passed is True
        assert outcome.cashout_plies == 1

    def test_delayed_cashout_counted(self):
        # exd5 Qxd5 Nc3 (Q moves) Nxd5 — nonsense chess, legal sequence; the
        # user's material only improves at ply 1 here, so craft a quiet-then-
        # capture PV instead: Nf3 e5-pawn falls at ply 3.
        board = board_after("e4", "e5", "Nc3", "Nc6")
        best = move_eval(board, "Nf3", 58.0, pv_sans=["a6", "Nxe5"])
        engine = FakeEngine(tops={board.epd(): [
            best,
            move_eval(board, "a3", 44.0),
            move_eval(board, "d3", 43.0),
        ]})
        outcome = run_gates(make_moment(board, ply=13, wp_before=58.0), engine)
        assert outcome.passed is True
        assert outcome.cashout_plies == 3

    def test_short_mate_passes_long_mate_rejected(self):
        board = board_after("e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6")
        mate_board = board.copy()
        mate_board.push_san("Qxf7")
        assert mate_board.is_checkmate()  # verify before asserting on gates

        def engine_with(mate_in):
            return FakeEngine(tops={board.epd(): [
                move_eval(board, "Qxf7", 100.0, mate_in=mate_in),
                move_eval(board, "Bxf7", 55.0),
                move_eval(board, "d3", 50.0),
            ]})

        good = run_gates(make_moment(board, ply=11, wp_before=90.0),
                         engine_with(1))
        assert good.passed is True
        assert good.cashout_plies == 1 and good.mate_in == 1

        deep = run_gates(make_moment(board, ply=11, wp_before=90.0),
                         engine_with(6))
        assert deep.rejection_gate == 2


class TestAcceptedEvidence:
    def test_full_outcome_shape_with_two_solutions(self):
        board = board_after("e4", "d5")
        engine = FakeEngine(tops={board.epd(): [
            move_eval(board, "exd5", 58.0, pv_sans=["Qxd5", "Nc3"]),
            move_eval(board, "e5", 55.0),      # within band — second solution
            move_eval(board, "Nc3", 44.0),     # best non-solution, gap 14
        ]})
        outcome = run_gates(make_moment(board, ply=12, wp_before=58.0), engine)
        assert isinstance(outcome, GateOutcome) and outcome.passed
        assert outcome.uniqueness_gap_wp == pytest.approx(14.0)
        assert [s["san"] for s in outcome.solutions] == ["exd5", "e5"]
        first = outcome.solutions[0]
        assert first["uci"] == "e4d5" and first["win_pct"] == 58.0
        assert first["pv_uci"][0] == "e4d5" and len(first["pv_uci"]) == 3
