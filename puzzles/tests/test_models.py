"""Schema smoke tests: seeds, constraints, and the JSON shapes the serving
layer depends on."""

import pytest
from django.db import IntegrityError
from django.utils import timezone

from games.models import Game
from puzzles.models import Candidate, MotifTag, Occurrence, Puzzle

pytestmark = pytest.mark.django_db


def make_game(**overrides) -> Game:
    defaults = dict(
        chesscom_uuid="test-uuid-1", url="https://www.chess.com/game/live/1",
        pgn="1. e4 e5", end_time=timezone.now(), time_class="blitz",
        time_control="300+2", user_color="white", user_rating=1500,
        opponent_username="opponent", opponent_rating=1490, result="loss",
    )
    defaults.update(overrides)
    return Game.objects.create(**defaults)


def make_puzzle(**overrides) -> Puzzle:
    defaults = dict(
        fen="r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3",
        position_key="a" * 64, puzzle_type="avoid", direction="allowed",
        win_pct_before=55.0,
        solutions=[{"uci": "g8f6", "san": "Nf6", "win_pct": 54.0,
                    "pv_uci": ["g8f6", "d2d3"]}],
        uniqueness_gap_wp=12.0, shallow_depth_stable=True, shallow_depth_used=10,
        cashout_plies=4, phase="opening", quality_score=1.0,
    )
    defaults.update(overrides)
    return Puzzle.objects.create(**defaults)


def test_motif_taxonomy_seeded():
    assert MotifTag.objects.count() == 14
    assert MotifTag.objects.filter(tier=MotifTag.Tier.RULE).count() == 10
    assert MotifTag.objects.get(slug="other").tier == MotifTag.Tier.FUZZY


def test_solutions_json_round_trip():
    puzzle = make_puzzle()
    puzzle.refresh_from_db()
    assert puzzle.solutions[0]["pv_uci"] == ["g8f6", "d2d3"]


def test_position_key_unique():
    make_puzzle()
    with pytest.raises(IntegrityError):
        make_puzzle()


def test_occurrence_unique_per_game_ply_and_distinct_game_recurrence():
    game = make_game()
    puzzle = make_puzzle()
    Occurrence.objects.create(puzzle=puzzle, game=game, ply=12, played_uci="d8h4",
                              played_san="Qh4", win_pct_after_played=30.0)
    # Same position later in the SAME game (repetition) — allowed as a row...
    Occurrence.objects.create(puzzle=puzzle, game=game, ply=16, played_uci="d8h4",
                              played_san="Qh4", win_pct_after_played=30.0)
    # ...but recurrence counts distinct games, not rows.
    assert puzzle.occurrences.count() == 2
    assert puzzle.occurrence_count == 1
    with pytest.raises(IntegrityError):
        Occurrence.objects.create(puzzle=puzzle, game=game, ply=12,
                                  played_uci="d8h4", played_san="Qh4",
                                  win_pct_after_played=30.0)


def test_candidate_ledger_keeps_rejections():
    game = make_game()
    Candidate.objects.create(
        game=game, ply=8, position_key="b" * 64, fen="startpos-ish",
        candidate_type="avoid", played_uci="f2f3", played_san="f3",
        win_pct_before=15.0, win_pct_after_played=5.0,
        verdict=Candidate.Verdict.REJECTED, rejection_gate=1,
    )
    assert Candidate.objects.filter(verdict="rejected", puzzle__isnull=True).exists()


def test_wp_drop_derived():
    game = make_game()
    puzzle = make_puzzle(win_pct_before=60.0)
    occ = Occurrence.objects.create(puzzle=puzzle, game=game, ply=10,
                                    played_uci="a2a3", played_san="a3",
                                    win_pct_after_played=35.0)
    assert occ.wp_drop == 25.0
