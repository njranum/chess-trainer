"""
Stateless line evaluation (Design.md §8): the client resubmits its full move
list on every POST; this module replays it from the puzzle FEN and rules.
Pure — no models, no clock, no session state.

A solve is the line, not one move: the first move checks against the
solution set; subsequent moves check against THAT solution's PV, with
opponent replies taken from the same PV, capped at MAX_USER_MOVES.
V1 accepts only the PV after move one; anything else is verdict "wrong"
and the per-move log on the Attempt is the near-miss dataset that decides
whether a tolerance band ever ships.
"""

import math
from dataclasses import dataclass, field

import chess

from puzzles.constants import MAX_USER_MOVES


class IllegalLine(Exception):
    """A submitted move is not legal in its position — client bug or abuse;
    the server is the sole authority (CLAUDE.md invariant)."""


@dataclass
class LineVerdict:
    status: str                      # "continue" | "solved" | "failed"
    moves_log: list[dict] = field(default_factory=list)
    #   [{"uci", "verdict": "solution"|"pv"|"wrong"}] — user moves only
    opponent_reply_uci: str | None = None   # set when status == "continue"
    failed_at_ply: int | None = None        # 1-based user-move index


def required_user_moves(pv: list[str], cashout_plies: int | None) -> int:
    line_plies = min(len(pv), cashout_plies or len(pv))
    return max(1, min(math.ceil(line_plies / 2), MAX_USER_MOVES))


def evaluate_line(fen: str, solutions: list[dict], cashout_plies: int | None,
                  moves: list[str]) -> LineVerdict:
    if not moves:
        raise IllegalLine("empty move list")

    board = chess.Board(fen)
    _check_legal(board, moves[0])

    solution = next((s for s in solutions if s["uci"] == moves[0]), None)
    if solution is None:
        return LineVerdict(status="failed",
                           moves_log=[{"uci": moves[0], "verdict": "wrong"}],
                           failed_at_ply=1)

    pv = solution.get("pv_uci") or [solution["uci"]]
    required = required_user_moves(pv, cashout_plies)
    log = []

    for i, user_uci in enumerate(moves):
        expected = pv[2 * i] if 2 * i < len(pv) else None
        _check_legal(board, user_uci)
        if i == 0 or user_uci == expected:
            log.append({"uci": user_uci,
                        "verdict": "solution" if i == 0 else "pv"})
        else:
            log.append({"uci": user_uci, "verdict": "wrong"})
            return LineVerdict(status="failed", moves_log=log,
                               failed_at_ply=i + 1)
        board.push(chess.Move.from_uci(user_uci))

        if i + 1 >= required:
            return LineVerdict(status="solved", moves_log=log)

        reply_idx = 2 * i + 1
        if reply_idx >= len(pv):        # PV exhausted early — line complete
            return LineVerdict(status="solved", moves_log=log)
        reply = pv[reply_idx]
        if i + 1 == len(moves):         # reply to the newest move only
            return LineVerdict(status="continue", moves_log=log,
                               opponent_reply_uci=reply)
        board.push(chess.Move.from_uci(reply))

    raise IllegalLine("more moves submitted than the line asks for")


def _check_legal(board: chess.Board, uci: str) -> None:
    try:
        move = chess.Move.from_uci(uci)
    except ValueError as exc:
        raise IllegalLine(f"unparseable move {uci!r}") from exc
    if move not in board.legal_moves:
        raise IllegalLine(f"illegal move {uci} in {board.fen()}")
