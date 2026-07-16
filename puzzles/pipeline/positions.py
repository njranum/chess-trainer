"""
Puzzle identity: the normalized position key (Design.md §6).

Identity is the position alone — placement, side to move, castling rights,
and en passant *only when a legal ep capture actually exists*. Both known
silent-dedup traps are handled here:
- move counters stripped (identical positions at different game depths);
- vestigial ep squares dropped (any double push sets the FEN ep field even
  when no capture is possible).
"""

import hashlib

import chess


def position_key(position: chess.Board | str) -> str:
    """Normalized position → 64-char hex key (sha256 of the canonical EPD)."""
    board = chess.Board(position) if isinstance(position, str) else position
    epd = board.epd(en_passant="legal")  # no counters; ep only if capturable
    return hashlib.sha256(epd.encode("ascii")).hexdigest()
