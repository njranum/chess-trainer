"""Writer + analyze orchestration tests (Design.md §6 collision policy, §4
gate-5 dedup, opening-leak promotion, §7 per-game transactions and
idempotency). Engine is always the scripted fake."""

import chess
import chess.pgn
import pytest
from django.utils import timezone

from games.models import Game
from puzzles.models import Candidate, Occurrence, Puzzle
from puzzles.pipeline.analyze import (
    analyze_game,
    analyze_pending,
    requeue_analyzed,
    requeue_failed,
)
from puzzles.pipeline.engine import MoveEval, PositionEval
from puzzles.pipeline.writer import quality_score
from puzzles.tests.fakes import FakeEngine

pytestmark = pytest.mark.django_db

# The canonical scenario: eight shuffle plies push the moment past the book
# cutoff, then 5.e4 f5?? 6.a3?? drops 22 wp. The puzzle position is after
# ...f5 (white to move), where exf5 wins a genuinely undefended pawn
# (SEE +1 — the knight shuffle keeps black's defenders home).
SHUFFLE_SANS = ["Nf3", "Na6", "Ng1", "Nb8", "Nf3", "Na6", "Ng1", "Nb8",
                "e4", "f5", "a3"]
WPS = [52.0] * 11 + [30.0]


def build_pgn(sans):
    game = chess.pgn.Game()
    node = game
    board = chess.Board()
    for san in sans:
        move = board.parse_san(san)
        board.push(move)
        node = node.add_variation(move)
    return str(game), board


def scenario_engine(movetime_ms=100, best_wp=58.0) -> FakeEngine:
    _, _ = build_pgn(SHUFFLE_SANS)  # sanity: the line is legal
    board = chess.Board()
    evals = {board.epd(): PositionEval(wp=WPS[0], mate_in=None)}
    for san, wp in zip(SHUFFLE_SANS, WPS[1:], strict=True):
        board.push_san(san)
        evals[board.epd()] = PositionEval(wp=wp, mate_in=None)

    puzzle_board = chess.Board()
    for san in SHUFFLE_SANS[:-1]:
        puzzle_board.push_san(san)

    def me(san, wp, pv_sans=()):
        working = puzzle_board.copy()
        first = working.parse_san(san)
        pv = [first]
        working.push(first)
        for s in pv_sans:
            m = working.parse_san(s)
            pv.append(m)
            working.push(m)
        return MoveEval(move=first, wp=wp, mate_in=None, pv=pv)

    tops = {puzzle_board.epd(): [
        me("exf5", best_wp, pv_sans=["d6"]),
        me("Nc3", best_wp - 13),
        me("d4", best_wp - 14),
    ]}
    engine = FakeEngine(evals=evals, tops=tops)
    engine.movetime_ms = movetime_ms
    return engine


def make_game(uuid="g1", movetime=None, **overrides):
    pgn, _ = build_pgn(SHUFFLE_SANS)
    defaults = dict(
        chesscom_uuid=uuid, url=f"https://chess.com/{uuid}", pgn=pgn,
        end_time=timezone.now(), time_class="blitz", time_control="300",
        user_color="white", user_rating=1500, opponent_username="opp",
        opponent_rating=1500, result="loss",
    )
    defaults.update(overrides)
    return Game.objects.create(**defaults)


class TestAnalyzeGame:
    def test_accepted_candidate_creates_full_graph(self):
        game = make_game()
        counts = analyze_game(game, scenario_engine())
        assert counts == {"candidates": 1, "puzzles": 1}

        game.refresh_from_db()
        assert game.analysis_status == "analyzed"
        assert game.engine_version == "fake engine 1.0"
        assert game.engine_movetime_ms == 100
        assert game.pipeline_version == "1"

        puzzle = Puzzle.objects.get()
        assert puzzle.puzzle_type == "avoid"
        assert puzzle.solutions[0]["san"] == "exf5"
        assert puzzle.win_pct_before == 52.0
        assert puzzle.engine_movetime_ms == 100
        assert "hanging-piece" in set(
            puzzle.motifs.values_list("slug", flat=True))
        assert puzzle.direction == "missed"  # winning capture existed

        occurrence = Occurrence.objects.get()
        assert occurrence.ply == 11 and occurrence.played_san == "a3"
        assert occurrence.wp_drop == pytest.approx(22.0)

        candidate = Candidate.objects.get()
        assert candidate.verdict == "accepted" and candidate.puzzle == puzzle

    def test_reanalysis_is_idempotent(self):
        game = make_game()
        analyze_game(game, scenario_engine())
        analyze_game(game, scenario_engine())  # same regime, run twice
        assert Puzzle.objects.count() == 1
        assert Occurrence.objects.count() == 1
        assert Candidate.objects.count() == 1

    def test_same_position_across_games_is_one_puzzle(self):
        analyze_game(make_game("g1"), scenario_engine())
        analyze_game(make_game("g2"), scenario_engine())
        puzzle = Puzzle.objects.get()
        assert puzzle.occurrence_count == 2
        # Recurrence promotes quality: 2 games > 1 game, all else equal.
        assert puzzle.quality_score == pytest.approx(
            quality_score(22.0, 13.0, 1, 2))

    def test_deeper_reanalysis_overwrites_shallower_does_not(self):
        analyze_game(make_game("g1"), scenario_engine(movetime_ms=100))
        original = Puzzle.objects.get()
        assert original.solutions[0]["win_pct"] == 58.0

        analyze_game(make_game("g2"), scenario_engine(movetime_ms=200,
                                                      best_wp=62.0))
        deeper = Puzzle.objects.get()
        assert deeper.solutions[0]["win_pct"] == 62.0   # overwritten
        assert deeper.engine_movetime_ms == 200

        analyze_game(make_game("g3"), scenario_engine(movetime_ms=50,
                                                      best_wp=40.0))
        unchanged = Puzzle.objects.get()
        assert unchanged.solutions[0]["win_pct"] == 62.0  # frozen
        assert unchanged.occurrence_count == 3            # but accumulated


class TestQueueMechanics:
    def test_failure_goes_failed_and_the_queue_continues(self):
        bad = make_game("bad")
        bad.pgn = "1. e4 e5"  # engine has no script for these positions
        bad.save()
        good = make_game("good")
        counts = analyze_pending(scenario_engine())
        assert counts["games"] == 1 and counts["failed"] == 1
        bad.refresh_from_db()
        good.refresh_from_db()
        assert bad.analysis_status == "failed" and bad.analysis_failures == 1
        assert "KeyError" in bad.analysis_error
        assert good.analysis_status == "analyzed"

    def test_three_strikes(self):
        game = make_game("flaky")
        game.analysis_status = Game.AnalysisStatus.FAILED
        game.analysis_failures = 2
        game.save()
        assert requeue_failed() == 1        # 2 < 3: back in the queue
        game.refresh_from_db()
        assert game.analysis_status == "pending"
        game.analysis_status = Game.AnalysisStatus.FAILED
        game.analysis_failures = 3
        game.save()
        assert requeue_failed() == 0        # three strikes stays failed

    def test_reanalyze_requeues(self):
        game = make_game()
        analyze_game(game, scenario_engine())
        assert requeue_analyzed() == 1
        game.refresh_from_db()
        assert game.analysis_status == "pending"

    def test_reanalyze_respects_version_filter(self):
        game = make_game()
        analyze_game(game, scenario_engine())  # pipeline_version == "1"
        assert requeue_analyzed(before_pipeline_version="1") == 0
        assert requeue_analyzed(before_pipeline_version="2") == 1


class TestOpeningLeakPromotion:
    def build_book_game(self, uuid):
        # 1.e4 e5 2.Qh5?? at ply 3 — book territory (ply < 10).
        sans = ["e4", "e5", "Qh5"]
        pgn, _ = build_pgn(sans)
        board = chess.Board()
        evals = {board.epd(): PositionEval(wp=52.0, mate_in=None)}
        for san, wp in zip(sans, [52.0, 52.0, 30.0], strict=True):
            board.push_san(san)
            evals[board.epd()] = PositionEval(wp=wp, mate_in=None)

        puzzle_board = chess.Board()
        puzzle_board.push_san("e4")
        puzzle_board.push_san("e5")

        def me(san, wp, pv_sans=()):
            working = puzzle_board.copy()
            first = working.parse_san(san)
            pv = [first]
            working.push(first)
            for s in pv_sans:
                m = working.parse_san(s)
                pv.append(m)
                working.push(m)
            return MoveEval(move=first, wp=wp, mate_in=None, pv=pv)

        # Nxe5?? isn't real chess advice — it's a scripted "best move that
        # cashes out" so gate 2 can pass in the fixture.
        tops = {puzzle_board.epd(): [
            me("Nf3", 58.0, pv_sans=["Nc6", "Nxe5"]),
            me("Nc3", 45.0),
            me("Bc4", 44.0),
        ]}
        engine = FakeEngine(evals=evals, tops=tops)
        game = Game.objects.create(
            chesscom_uuid=uuid, url=f"https://chess.com/{uuid}", pgn=pgn,
            end_time=timezone.now(), time_class="blitz", time_control="300",
            user_color="white", user_rating=1500, opponent_username="opp",
            opponent_rating=1500, result="loss",
        )
        return game, engine

    def test_first_two_rejected_third_promotes_and_backfills(self):
        for uuid in ("bk1", "bk2"):
            game, engine = self.build_book_game(uuid)
            analyze_game(game, engine)
        assert Puzzle.objects.count() == 0
        assert Candidate.objects.filter(verdict="rejected",
                                        rejection_gate=4).count() == 2

        game3, engine3 = self.build_book_game("bk3")
        analyze_game(game3, engine3)

        puzzle = Puzzle.objects.get()
        assert puzzle.is_opening_leak is True
        assert puzzle.occurrence_count == 3      # two backfilled + current
        assert Candidate.objects.filter(verdict="accepted",
                                        puzzle=puzzle).count() == 3
        assert Candidate.objects.filter(verdict="rejected").count() == 0
