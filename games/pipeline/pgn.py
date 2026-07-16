"""
chess.com game JSON + PGN → Game model fields (Design.md §7 stage 1).

Most facts come from the game JSON (ratings, usernames, time control); the
PGN supplies ECO/opening and, later at analyze time, per-ply clocks. Clock
data (%clk) lives in PGN comments and some older/daily games lack it —
absence is surfaced as None, never fabricated.
"""

import io
from datetime import UTC, datetime

import chess.pgn


def parse_game(game_json: dict, username: str) -> dict | None:
    """Game-JSON dict → Game field dict, or None if the game is not usable
    (a chess variant, or missing its PGN)."""
    if game_json.get("rules") != "chess" or not game_json.get("pgn"):
        return None

    username = username.lower()
    white, black = game_json["white"], game_json["black"]
    if white["username"].lower() == username:
        user_color, user_side, opp_side = "white", white, black
    elif black["username"].lower() == username:
        user_color, user_side, opp_side = "black", black, white
    else:
        return None  # not this user's game — shouldn't happen, skip loudly

    if user_side["result"] == "win":
        result = "win"
    elif opp_side["result"] == "win":
        result = "loss"
    else:
        result = "draw"  # agreed / repetition / stalemate / insufficient / 50move

    headers = _pgn_headers(game_json["pgn"])

    return {
        "chesscom_uuid": game_json["uuid"],
        "url": game_json.get("url", ""),
        "pgn": game_json["pgn"],
        "end_time": datetime.fromtimestamp(game_json["end_time"], tz=UTC),
        "time_class": game_json["time_class"],
        "time_control": game_json.get("time_control", ""),
        "rated": bool(game_json.get("rated", True)),
        "user_color": user_color,
        "user_rating": user_side["rating"],
        "opponent_username": opp_side["username"],
        "opponent_rating": opp_side["rating"],
        "result": result,
        "eco": headers.get("ECO", "")[:3],
        "opening_name": _opening_from_eco_url(headers.get("ECOUrl", "")),
    }


def _pgn_headers(pgn: str) -> dict:
    game = chess.pgn.read_game(io.StringIO(pgn))
    return dict(game.headers) if game else {}


def _opening_from_eco_url(eco_url: str) -> str:
    # ".../openings/Sicilian-Defense-2.Nf3-d6" → "Sicilian Defense 2.Nf3 d6"
    if "/openings/" not in eco_url:
        return ""
    return eco_url.rstrip("/").split("/openings/")[-1].replace("-", " ")[:120]


def clocks_by_ply(pgn: str) -> dict[int, float]:
    """{1-based ply → remaining seconds} from %clk comments.

    Plies without clock data are simply absent (older/daily games) — callers
    must handle missing keys, not assume 0.
    """
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None:
        return {}
    clocks: dict[int, float] = {}
    ply = 0
    for node in game.mainline():
        ply += 1
        clock = node.clock()
        if clock is not None:
            clocks[ply] = clock
    return clocks
