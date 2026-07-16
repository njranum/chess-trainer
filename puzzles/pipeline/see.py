"""
Static exchange evaluation (Design.md §5 Tier-1; the CLAUDE.md known-hard
gotcha: python-chess has no SEE built in).

Implementation choice: exact minimax over the capture tree on ONE square,
using real board copies and legal moves. Slower than bitboard swap-off but
exact where the classic algorithm approximates — pins are respected because
an illegally-pinned defender simply has no legal recapture, and x-rays
appear naturally as the board empties. Capture chains are short, so the
exponential worst case never bites at our scale (a handful of candidates
per game).
"""

import chess

from puzzles.pipeline.material import PIECE_VALUES


def see(board: chess.Board, move: chess.Move) -> int:
    """Expected material outcome (pawns, mover's perspective) of playing
    `move`, assuming optimal capture/stand-pat play on the target square.

    `move` must be legal. Non-captures score the exchange risk of landing on
    the square (0 if the square is safe, negative if the piece can be won).
    """
    if move not in board.legal_moves:
        raise ValueError(f"illegal move {move} in {board.fen()}")

    gain = 0
    if board.is_en_passant(move):
        gain = PIECE_VALUES[chess.PAWN]
    elif board.is_capture(move):
        gain = PIECE_VALUES[board.piece_at(move.to_square).piece_type]
    if move.promotion:
        gain += PIECE_VALUES[move.promotion] - PIECE_VALUES[chess.PAWN]

    occupant_value = PIECE_VALUES[move.promotion or
                                  board.piece_at(move.from_square).piece_type]
    working = board.copy()
    working.push(move)
    return gain - _best_exchange(working, move.to_square, occupant_value)


def _best_exchange(board: chess.Board, square: chess.Square,
                   occupant_value: int) -> int:
    """Best value the side to move can extract by (optionally) capturing on
    `square`. Stand-pat floor of 0: nobody is forced to lose material."""
    best = 0
    for move in board.legal_moves:
        if move.to_square != square or not board.is_capture(move):
            continue
        attacker_value = PIECE_VALUES[move.promotion or
                                      board.piece_at(move.from_square).piece_type]
        promo_bonus = 0
        if move.promotion:
            promo_bonus = PIECE_VALUES[move.promotion] - PIECE_VALUES[chess.PAWN]
        working = board.copy()
        working.push(move)
        value = (occupant_value + promo_bonus
                 - _best_exchange(working, square, attacker_value))
        best = max(best, value)
    return best


def best_capture_gain(board: chess.Board, square: chess.Square) -> int:
    """Best SEE over all legal captures on `square` by the side to move
    (0 if there is no capture, or every capture loses material)."""
    gains = [see(board, m) for m in board.legal_moves
             if m.to_square == square and board.is_capture(m)]
    return max(gains, default=0)
