"""position_key must collapse both known dedup traps (Design.md §6, CLAUDE.md
gotchas): move counters and vestigial en-passant squares. Positions are built
with python-chess moves, never invented FENs."""

import chess

from puzzles.pipeline.positions import position_key


def board_after(*sans: str) -> chess.Board:
    board = chess.Board()
    for san in sans:
        board.push_san(san)
    return board


def test_key_shape():
    key = position_key(chess.Board())
    assert len(key) == 64 and int(key, 16) >= 0  # 64 hex chars (model max_length)


def test_move_counters_do_not_split_identity():
    board = board_after("e4", "e5", "Nf3", "Nc6")
    parts = board.fen().split(" ")
    assert parts[4:] != ["0", "1"]  # sanity: counters really differ below
    doctored = " ".join(parts[:4] + ["0", "1"])
    assert position_key(doctored) == position_key(board)


def test_vestigial_ep_square_does_not_split_identity():
    # After 1.e4 the FEN ep field may say e3, but no black pawn can capture.
    with_ep = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
    without = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    assert position_key(with_ep) == position_key(without)


def test_legal_ep_is_part_of_identity():
    # 1.e4 d5 2.e5 f5: exf6 en passant is genuinely legal — the ep right is
    # real information and MUST distinguish the position.
    board = board_after("e4", "d5", "e5", "f5")
    assert any(board.is_en_passant(m) for m in board.legal_moves)
    stripped = board.fen().split(" ")
    stripped[3] = "-"
    assert position_key(" ".join(stripped)) != position_key(board)


def test_side_to_move_and_castling_matter():
    initial = chess.Board()
    flipped = " ".join(["rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR", "w", "KQq", "-", "0", "1"])
    assert position_key(flipped) != position_key(initial)  # castling rights differ
    after_moves = board_after("Nf3", "Nf6", "Ng1", "Ng8")  # same placement, same turn
    assert position_key(after_moves) == position_key(initial)


def test_different_positions_differ():
    assert position_key(board_after("e4")) != position_key(board_after("d4"))


def test_board_and_fen_inputs_agree():
    board = board_after("e4", "c5")
    assert position_key(board) == position_key(board.fen())
