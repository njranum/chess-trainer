"""Client tests over recorded fixtures — no network."""

import json
import pathlib
from datetime import UTC, datetime

import pytest

from games.pipeline.chesscom import ChesscomClient

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    """Serves the recorded fixtures; counts requests per URL."""

    def __init__(self):
        self.headers = {}
        self.requested = []
        self.routes = {
            "https://api.chess.com/pub/player/snoopy/games/archives":
                json.loads((FIXTURES / "archives.json").read_text()),
            "https://api.chess.com/pub/player/snoopy/games/2026/06":
                json.loads((FIXTURES / "month_2026_06.json").read_text()),
            "https://api.chess.com/pub/player/snoopy/games/2026/05":
                {"games": []},
        }

    def get(self, url, timeout=None):
        self.requested.append(url)
        return FakeResponse(self.routes[url])


@pytest.fixture
def client():
    return ChesscomClient("Snoopy", session=FakeSession())


def test_username_normalized_and_required(client):
    assert client.username == "snoopy"
    with pytest.raises(ValueError):
        ChesscomClient("")


def test_archive_months_sorted(client):
    assert client.archive_months() == [(2026, 5), (2026, 6)]


def test_month_games(client):
    games = client.month_games(2026, 6)
    assert len(games) == 4
    assert games[0]["uuid"] == "uuid-a"


def test_months_to_fetch_backfill(client):
    assert client.months_to_fetch((2026, 5)) == [(2026, 5), (2026, 6)]
    assert client.months_to_fetch((2026, 6)) == [(2026, 6)]


def test_months_to_fetch_steady_state_is_current_plus_previous(client):
    now = datetime(2026, 6, 20, tzinfo=UTC)
    assert client.months_to_fetch(None, now=now) == [(2026, 5), (2026, 6)]
    # Immutability rule: months before the previous one are never re-fetched.
    later = datetime(2026, 9, 1, tzinfo=UTC)
    assert client.months_to_fetch(None, now=later) == []


def test_year_rollover_previous_month():
    client = ChesscomClient("snoopy", session=FakeSession())
    client.session.routes["https://api.chess.com/pub/player/snoopy/games/archives"] = {
        "archives": ["https://api.chess.com/pub/player/snoopy/games/2025/12",
                     "https://api.chess.com/pub/player/snoopy/games/2026/01"]
    }
    now = datetime(2026, 1, 2, tzinfo=UTC)
    assert client.months_to_fetch(None, now=now) == [(2025, 12), (2026, 1)]


def test_polite_user_agent(client):
    assert "chess-trainer" in client.session.headers["User-Agent"]
