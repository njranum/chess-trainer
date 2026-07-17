"""Serving order (Design.md §8): overdue first, then new-by-quality under
the daily cap, buried excluded, soft-mix preferring the type trained less."""

from datetime import timedelta

import pytest
from django.utils import timezone

from puzzles.models import Puzzle
from training.models import Attempt
from training.serving import new_puzzles_started_today, next_puzzle

pytestmark = pytest.mark.django_db


def make_puzzle(key, quality=1.0, puzzle_type="avoid", due_at=None,
                buried_until=None):
    return Puzzle.objects.create(
        fen="rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        position_key=key.ljust(64, "0"), puzzle_type=puzzle_type,
        direction="allowed", win_pct_before=55.0,
        solutions=[{"uci": "e4d5", "san": "exd5", "win_pct": 55.0,
                    "pv_uci": ["e4d5"]}],
        uniqueness_gap_wp=12.0, shallow_depth_stable=True,
        shallow_depth_used=10, cashout_plies=1, phase="middlegame",
        quality_score=quality, due_at=due_at, buried_until=buried_until,
    )


def test_overdue_beats_new_and_orders_by_due_then_quality():
    now = timezone.now()
    make_puzzle("new", quality=99.0)
    older = make_puzzle("older", quality=0.1, due_at=now - timedelta(days=2))
    make_puzzle("newer", quality=50.0, due_at=now - timedelta(days=1))
    assert next_puzzle() == older  # earliest due wins regardless of quality


def test_future_due_is_not_served():
    make_puzzle("future", due_at=timezone.now() + timedelta(days=3))
    assert next_puzzle() is None or next_puzzle().due_at is None


def test_new_by_quality_when_nothing_due():
    make_puzzle("low", quality=0.1)
    high = make_puzzle("high", quality=9.0)
    assert next_puzzle() == high


def test_buried_excluded_everywhere():
    now = timezone.now()
    make_puzzle("buried-due", due_at=now - timedelta(days=1),
                buried_until=now + timedelta(days=30))
    make_puzzle("buried-new", buried_until=now + timedelta(days=30))
    survivor = make_puzzle("alive", quality=0.5)
    assert next_puzzle() == survivor

    expired = make_puzzle("expired", quality=99.0,
                          buried_until=now - timedelta(days=1))
    assert next_puzzle() == expired  # burial wears off


def test_daily_cap_counts_first_attempts_today():
    for i in range(10):
        puzzle = make_puzzle(f"cap{i}")
        Attempt.objects.create(puzzle=puzzle, moves=[], correct=True, grade=5)
    assert new_puzzles_started_today(timezone.now()) == 10
    make_puzzle("eleventh", quality=9.9)
    assert next_puzzle() is None  # cap reached, nothing due → done for today


def test_old_puzzle_reviewed_today_does_not_count_toward_cap():
    puzzle = make_puzzle("veteran")
    old = Attempt.objects.create(puzzle=puzzle, moves=[], correct=True, grade=4)
    Attempt.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=5))
    Attempt.objects.create(puzzle=puzzle, moves=[], correct=True, grade=5)
    assert new_puzzles_started_today(timezone.now()) == 0


def test_soft_mix_prefers_the_type_trained_less():
    avoid = make_puzzle("avoid-one", quality=9.0, puzzle_type="avoid")
    punish = make_puzzle("punish-one", quality=8.0, puzzle_type="punish")
    Attempt.objects.create(puzzle=avoid, moves=[], correct=True, grade=5)
    # One avoid trained today, zero punish → punish preferred despite quality.
    assert next_puzzle() == punish
