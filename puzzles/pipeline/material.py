"""Shared material accounting for gates, SEE, and detectors."""

import chess

PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
                chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


def material_balance(board: chess.Board, color: chess.Color) -> int:
    """Total material for `color` minus the opponent's, in pawns."""
    balance = 0
    for piece in board.piece_map().values():
        value = PIECE_VALUES[piece.piece_type]
        balance += value if piece.color == color else -value
    return balance
