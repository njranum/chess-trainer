"""Snapshot stage: delete-and-recompute idempotency, window boundaries, and
the two sides of the games-vs-training gap."""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from dashboard.models import WeaknessSnapshot
from dashboard.pipeline.snapshot import take_snapshot
from games.models import Game, PipelineRun
from puzzles.models import MotifTag, Occurrence, Puzzle, PuzzleMotif
from training.models import Attempt

pytestmark = pytest.mark.django_db


@pytest.fixture
def corpus():
    now = timezone.now()
    tag = MotifTag.objects.get(slug="fork")

    def game(uuid, days_ago):
        return Game.objects.create(
            chesscom_uuid=uuid, url="x", pgn="1. e4",
            end_time=now - timedelta(days=days_ago), time_class="blitz",
            time_control="300", user_color="white", user_rating=1500,
            opponent_username="o", opponent_rating=1500, result="loss",
        )

    puzzle = Puzzle.objects.create(
        fen="rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        position_key="s" * 64, puzzle_type="avoid", direction="missed",
        win_pct_before=55.0,
        solutions=[{"uci": "e4d5", "san": "exd5", "win_pct": 55.0,
                    "pv_uci": ["e4d5"]}],
        uniqueness_gap_wp=12.0, shallow_depth_stable=True,
        shallow_depth_used=10, cashout_plies=1, phase="middlegame",
        quality_score=1.0,
    )
    PuzzleMotif.objects.create(puzzle=puzzle, tag=tag, source="rule",
                               rule_verified=True)
    # Two occurrences inside the 30d window, one outside it.
    for uuid, days_ago, ply in (("in1", 5, 11), ("in2", 20, 13), ("out", 45, 15)):
        Occurrence.objects.create(puzzle=puzzle, game=game(uuid, days_ago),
                                  ply=ply, played_uci="a2a3", played_san="a3",
                                  win_pct_after_played=40.0)
    # Training side: two attempts in-window (one correct), one ancient.
    Attempt.objects.create(puzzle=puzzle, moves=[], correct=True, grade=5)
    Attempt.objects.create(puzzle=puzzle, moves=[], correct=False, grade=1)
    old = Attempt.objects.create(puzzle=puzzle, moves=[], correct=True, grade=5)
    Attempt.objects.filter(pk=old.pk).update(
        created_at=now - timedelta(days=40))
    return tag


def test_window_boundaries_and_both_sides(corpus):
    counts = take_snapshot()
    assert counts["tags"] == 14
    snap = WeaknessSnapshot.objects.get(tag=corpus,
                                        date=timezone.now().date())
    assert snap.occurrences_in_window == 2   # the 45-day-old one is out
    assert snap.games_in_window == 2
    assert snap.attempts == 2 and snap.correct == 1


def test_idempotent_delete_and_recompute(corpus):
    take_snapshot()
    take_snapshot()
    assert WeaknessSnapshot.objects.filter(
        date=timezone.now().date()).count() == 14


def test_command_writes_pipeline_run(corpus):
    call_command("snapshot")
    run = PipelineRun.objects.get(stage="snapshot")
    assert run.status == "succeeded"
    assert run.counts["tags"] == 14
