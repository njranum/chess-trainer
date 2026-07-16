"""Parser tests over the committed fixture month — both colours, all result
mappings, clock presence and absence, variant skipping."""

import io
import json
import pathlib

import chess.pgn
import pytest

from games.pipeline.pgn import clocks_by_ply, parse_game

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def month():
    games = json.loads((FIXTURES / "month_2026_06.json").read_text())["games"]
    return {g["uuid"]: g for g in games}


def test_fixture_pgns_are_legal(month):
    # The fixtures were machine-generated; prove it stayed true.
    for uuid in ("uuid-a", "uuid-b", "uuid-d"):
        game = chess.pgn.read_game(io.StringIO(month[uuid]["pgn"]))
        board = game.board()
        for move in game.mainline_moves():
            assert move in board.legal_moves
            board.push(move)


def test_user_white_win(month):
    fields = parse_game(month["uuid-a"], "snoopy")
    assert fields["user_color"] == "white"
    assert fields["result"] == "win"
    assert fields["user_rating"] == 1512
    assert fields["opponent_username"] == "villain99"
    assert fields["opponent_rating"] == 1498
    assert fields["eco"] == "C20"
    assert fields["opening_name"] == "Kings Pawn Opening Wayward Queen Attack"
    assert fields["time_class"] == "blitz"
    assert fields["end_time"].year >= 2025


def test_user_black_loss_case_insensitive(month):
    fields = parse_game(month["uuid-b"], "SNOOPY")  # case must not matter
    assert fields["user_color"] == "black"
    assert fields["result"] == "loss"
    assert fields["rated"] is False


def test_draw_mapping(month):
    assert parse_game(month["uuid-d"], "snoopy")["result"] == "draw"


def test_variant_skipped(month):
    assert parse_game(month["uuid-c"], "snoopy") is None


def test_missing_pgn_skipped(month):
    broken = dict(month["uuid-a"], pgn="")
    assert parse_game(broken, "snoopy") is None


def test_not_users_game_skipped(month):
    assert parse_game(month["uuid-a"], "somebody-else") is None


def test_clocks_present(month):
    clocks = clocks_by_ply(month["uuid-a"]["pgn"])
    assert clocks[1] == 298.5          # white's first move
    assert clocks[2] == 297.0          # black's reply
    assert len(clocks) == 7
    assert all(0 < c <= 300 for c in clocks.values())


def test_clocks_absent_is_empty_not_fabricated(month):
    assert clocks_by_ply(month["uuid-b"]["pgn"]) == {}
