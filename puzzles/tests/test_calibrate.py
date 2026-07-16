"""Calibration page: standalone HTML with board, prompt, solution line, and
gate evidence for each sampled puzzle."""

import pytest
from django.core.management import call_command
from django.utils import timezone

from games.models import Game
from puzzles.models import Occurrence, Puzzle
from puzzles.pipeline.calibrate import build_calibration_html

pytestmark = pytest.mark.django_db


@pytest.fixture
def puzzle_with_occurrence():
    game = Game.objects.create(
        chesscom_uuid="cal-1", url="https://chess.com/cal-1", pgn="1. e4",
        end_time=timezone.now(), time_class="blitz", time_control="300",
        user_color="white", user_rating=1500, opponent_username="rival",
        opponent_rating=1520, result="loss",
    )
    puzzle = Puzzle.objects.create(
        fen="rnbqkbnr/ppp2ppp/8/3pp3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 3",
        position_key="c" * 64, puzzle_type="punish", direction="missed",
        win_pct_before=62.0,
        solutions=[{"uci": "e4d5", "san": "exd5", "win_pct": 62.0,
                    "pv_uci": ["e4d5", "d8d5"]}],
        uniqueness_gap_wp=14.0, shallow_depth_stable=True,
        shallow_depth_used=10, cashout_plies=1, phase="opening",
        quality_score=0.05,
    )
    Occurrence.objects.create(
        puzzle=puzzle, game=game, ply=5, played_uci="g1f3", played_san="Nf3",
        win_pct_after_played=40.0, clock_seconds=95.0, clock_bucket="comfortable",
    )
    return puzzle


def test_page_contains_everything_needed_to_judge(puzzle_with_occurrence):
    page = build_calibration_html([puzzle_with_occurrence])
    assert "<svg" in page                                # the board
    assert "find the refutation you missed" in page.lower()  # PUNISH prompt
    assert "exd5" in page and "Qxd5" in page             # solution + PV in SAN
    assert "Nf3" in page                                 # what was played
    assert "14.0" in page and "62.0" in page             # gate evidence
    assert "rival" in page and "95s" in page             # the emotional context
    assert "1 game(s)" in page


def test_command_writes_standalone_file(puzzle_with_occurrence, tmp_path):
    out = tmp_path / "sample.html"
    call_command("calibrate", sample=10, out=str(out))
    content = out.read_text()
    assert content.startswith("<!doctype html>")
    assert "Calibration sample — 1 puzzles" in content
