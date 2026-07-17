"""The four read pages render from real data and the trends endpoint feeds
Chart.js the right shape."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from dashboard.pipeline.snapshot import take_snapshot
from games.models import Game, PipelineRun
from puzzles.models import MotifTag, Occurrence, Puzzle, PuzzleMotif
from training.models import Attempt

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(client):
    u = User.objects.create_superuser("nick", password="pw")
    client.force_login(u)
    return u


@pytest.fixture
def data():
    now = timezone.now()
    game = Game.objects.create(
        chesscom_uuid="p1", url="x", pgn="1. e4", end_time=now,
        time_class="blitz", time_control="300", user_color="white",
        user_rating=1500, opponent_username="o", opponent_rating=1500,
        result="loss", eco="C50", opening_name="Italian Game",
        analysis_status="failed", analysis_failures=3,
        analysis_error="Boom traceback",
    )
    puzzle = Puzzle.objects.create(
        fen="rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        position_key="p" * 64, puzzle_type="avoid", direction="missed",
        win_pct_before=55.0, is_opening_leak=True,
        solutions=[{"uci": "e4d5", "san": "exd5", "win_pct": 55.0,
                    "pv_uci": ["e4d5"]}],
        uniqueness_gap_wp=12.0, shallow_depth_stable=True,
        shallow_depth_used=10, cashout_plies=1, phase="opening",
        quality_score=1.0,
    )
    PuzzleMotif.objects.create(puzzle=puzzle, tag=MotifTag.objects.get(slug="fork"),
                               source="rule", rule_verified=True)
    Occurrence.objects.create(puzzle=puzzle, game=game, ply=11,
                              played_uci="a2a3", played_san="a3",
                              win_pct_after_played=35.0)
    Attempt.objects.create(puzzle=puzzle, moves=[], correct=True, grade=5)
    PipelineRun.objects.create(stage="analyze", status="succeeded",
                               counts={"games": 1})
    return puzzle


def test_dashboard_page(client, user, data):
    response = client.get("/dashboard/")
    content = response.content.decode()
    assert response.status_code == 200
    assert "Fork / double attack" in content     # the motif table
    assert "day streak" in content


def test_streak_counts_consecutive_days(client, user, data):
    yesterday = Attempt.objects.create(puzzle=data, moves=[], correct=True,
                                       grade=4)
    Attempt.objects.filter(pk=yesterday.pk).update(
        created_at=timezone.now() - timedelta(days=1))
    content = client.get("/dashboard/").content.decode()
    assert '<span class="stat-num">2</span> day streak' in content


def test_trends_json_shape(client, user, data):
    take_snapshot()
    payload = client.get("/dashboard/trends.json").json()
    assert payload["dates"] == [str(timezone.now().date())]
    fork = next(d for d in payload["occurrences"]
                if d["label"] == "Fork / double attack")
    assert fork["data"] == [1]
    assert payload["solve_rate"] == [100]


def test_openings_page_lists_leaks(client, user, data):
    content = client.get("/openings/").content.decode()
    assert "Italian Game" in content and "C50" in content
    assert "20.0" in content  # avg wp lost: 55 − 35


def test_archive_filters(client, user, data):
    assert "exd5" not in client.get("/puzzles/?type=punish").content.decode()
    content = client.get("/puzzles/?type=avoid&motif=fork").content.decode()
    assert "avoid · leak" in content


def test_games_health_page(client, user, data):
    content = client.get("/games/").content.decode()
    assert "analyze" in content            # the run row
    assert "Boom traceback" in content     # the failed game surfaces
