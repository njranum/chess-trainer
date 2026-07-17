"""Endpoint tests: auth lock, the /train/next payload, the full stateless
attempt flow (solve, fail, continue), SM-2 application, bury, report."""

import json
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from games.models import Game
from puzzles.models import Occurrence, Puzzle
from training.models import Attempt, Report

pytestmark = pytest.mark.django_db

FEN = "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2"


@pytest.fixture
def user(client):
    user = User.objects.create_superuser("nick", password="pw")
    client.force_login(user)
    return user


@pytest.fixture
def puzzle():
    game = Game.objects.create(
        chesscom_uuid="v-1", url="https://chess.com/game/v-1", pgn="1. e4 d5",
        end_time=timezone.now(), time_class="blitz", time_control="300",
        user_color="white", user_rating=1500, opponent_username="rival",
        opponent_rating=1520, result="loss",
    )
    puzzle = Puzzle.objects.create(
        fen=FEN, position_key="v" * 64, puzzle_type="avoid",
        direction="missed", win_pct_before=58.0,
        solutions=[{"uci": "e4d5", "san": "exd5", "win_pct": 58.0,
                    "pv_uci": ["e4d5", "d8d5", "b1c3"]}],
        uniqueness_gap_wp=13.0, shallow_depth_stable=True,
        shallow_depth_used=10, cashout_plies=6, phase="middlegame",
        quality_score=1.0,
    )
    Occurrence.objects.create(puzzle=puzzle, game=game, ply=3,
                              played_uci="a2a3", played_san="a3",
                              win_pct_after_played=36.0, clock_seconds=45.0,
                              clock_bucket="low")
    return puzzle


def post(client, path, body):
    return client.post(path, json.dumps(body), content_type="application/json")


class TestAuthLock:
    def test_anonymous_is_redirected(self, client, puzzle):
        response = client.get("/train/next")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_login_page_is_reachable(self, client):
        assert client.get("/accounts/login/").status_code == 200


class TestNext:
    def test_payload(self, client, user, puzzle):
        data = client.get("/train/next").json()
        assert data["puzzle_id"] == puzzle.pk
        assert data["fen"] == FEN
        assert data["orientation"] == "white"
        assert data["prompt"] == "Find the move you should have played."
        assert data["context"]["opponent"] == "rival"
        assert data["context"]["clock_seconds"] == 45.0
        assert data["hints"]["from_square"] == "e4"

    def test_done_when_empty(self, client, user):
        data = client.get("/train/next").json()
        assert data == {"done": True, "due_count": 0}


class TestAttemptFlow:
    def test_multi_move_solve(self, client, user, puzzle):
        # Move 1 → server replies from the PV; move 2 completes the line.
        first = post(client, "/train/attempt",
                     {"puzzle_id": puzzle.pk, "moves": ["e4d5"]}).json()
        assert first == {"status": "continue", "opponent_reply": "d8d5"}
        assert Attempt.objects.count() == 0  # mid-line: nothing recorded

        final = post(client, "/train/attempt",
                     {"puzzle_id": puzzle.pk, "moves": ["e4d5", "b1c3"],
                      "latency_ms": 8_000, "hints_used": 0}).json()
        assert final["status"] == "solved"
        assert final["grade"] == 5
        assert final["solution_line_san"] == ["exd5", "Qxd5", "Nc3"]

        puzzle.refresh_from_db()
        assert puzzle.repetitions == 1
        assert puzzle.due_at > timezone.now() + timedelta(hours=23)
        attempt = Attempt.objects.get()
        assert attempt.correct and attempt.grade == 5
        assert [m["verdict"] for m in attempt.moves] == ["solution", "pv"]

    def test_hint_prices_into_grade(self, client, user, puzzle):
        final = post(client, "/train/attempt",
                     {"puzzle_id": puzzle.pk, "moves": ["e4d5", "b1c3"],
                      "latency_ms": 8_000, "hints_used": 1}).json()
        assert final["grade"] == 3

    def test_fail_is_the_product(self, client, user, puzzle):
        data = post(client, "/train/attempt",
                    {"puzzle_id": puzzle.pk, "moves": ["g1f3"],
                     "latency_ms": 4_000}).json()
        assert data["status"] == "failed"
        assert data["failed_at_ply"] == 1
        assert data["solution_line_san"] == ["exd5", "Qxd5", "Nc3"]
        assert data["played_in_game"] == "a3"
        assert data["game_url"] == "https://chess.com/game/v-1"

        puzzle.refresh_from_db()
        assert puzzle.lapses == 1 and puzzle.repetitions == 0
        assert Attempt.objects.get().correct is False

    def test_illegal_move_is_rejected_and_unrecorded(self, client, user, puzzle):
        response = post(client, "/train/attempt",
                        {"puzzle_id": puzzle.pk, "moves": ["e4e6"]})
        assert response.status_code == 400
        assert Attempt.objects.count() == 0


class TestOperational:
    def test_bury_hides_without_touching_sm2(self, client, user, puzzle):
        puzzle.ease_factor = 2.1
        puzzle.save()
        post(client, "/train/bury", {"puzzle_id": puzzle.pk})
        puzzle.refresh_from_db()
        assert puzzle.buried_until > timezone.now() + timedelta(days=29)
        assert puzzle.ease_factor == 2.1
        assert client.get("/train/next").json()["done"] is True

    def test_report_creates_row(self, client, user, puzzle):
        post(client, "/train/report", {"puzzle_id": puzzle.pk,
                                       "note": "engine-only nonsense"})
        report = Report.objects.get()
        assert report.puzzle == puzzle
        assert report.note == "engine-only nonsense"
