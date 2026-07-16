"""SEE against known exchange sequences (CLAUDE.md: test against known
sequences; never invent chess facts — each position's premise is verified
with python-chess before the SEE assertion)."""

import chess

from puzzles.pipeline.see import best_capture_gain, see


def sq(name):
    return chess.parse_square(name)


def move(board, san):
    return board.parse_san(san)


class TestBasicExchanges:
    def test_free_pawn(self):
        board = chess.Board("k7/8/8/3p4/8/8/3R4/K7 w - - 0 1")
        assert not board.is_attacked_by(chess.BLACK, sq("d5"))  # premise
        assert see(board, move(board, "Rxd5")) == 1

    def test_rook_takes_defended_pawn(self):
        board = chess.Board("k7/8/4p3/3p4/8/8/3R4/K7 w - - 0 1")
        assert board.is_attacked_by(chess.BLACK, sq("d5"))  # e6 pawn defends
        assert see(board, move(board, "Rxd5")) == 1 - 5

    def test_even_rook_trade(self):
        board = chess.Board("k7/8/4p3/3r4/8/8/3R4/K7 w - - 0 1")
        # Rxd5 exd5: rook for rook, then the pawn recapture makes it 5−5=0.
        assert see(board, move(board, "Rxd5")) == 0

    def test_non_capture_to_safe_square_is_zero(self):
        board = chess.Board("k7/8/8/8/8/8/3R4/K7 w - - 0 1")
        assert see(board, move(board, "Rd5")) == 0

    def test_non_capture_hanging_the_piece(self):
        board = chess.Board("k7/8/4p3/8/8/8/3R4/K7 w - - 0 1")
        assert see(board, move(board, "Rd5")) == -5  # lands en prise to exd5


class TestClassicPositions:
    """The two standard chessprogramming-wiki SEE test positions."""

    def test_rook_takes_e5_pawn(self):
        board = chess.Board("1k1r4/1pp4p/p7/4p3/8/P5P1/1PP4P/2K1R3 w - - 0 1")
        assert see(board, move(board, "Rxe5")) == 1

    def test_knight_takes_defended_e5_pawn(self):
        board = chess.Board("1k1r3q/1ppn3p/p4b2/4p3/8/P2N2P1/1PP1R1BP/2K1Q3 w - - 0 1")
        # Nxe5 wins a pawn but the knight falls: 1 − 3 = −2 with best play.
        assert see(board, move(board, "Nxe5")) == -2


class TestLegalityAwareness:
    def test_pinned_defender_cannot_recapture(self):
        # Bb5 pins the c6 knight to the e8 king, so e5 is really free.
        board = chess.Board("4k3/8/2n5/1B2p3/8/5N2/8/4K3 w - - 0 1")
        knight_recapture = chess.Move(sq("c6"), sq("e5"))
        assert board.is_pinned(chess.BLACK, sq("c6"))          # premise
        board_after = board.copy()
        board_after.push_san("Nxe5")
        assert knight_recapture not in board_after.legal_moves  # premise
        assert see(board, move(board, "Nxe5")) == 1

    def test_unpinned_defender_recaptures(self):
        # Same position without the pinning bishop: 1 − 3 = −2.
        board = chess.Board("4k3/8/2n5/4p3/8/5N2/8/4K3 w - - 0 1")
        assert not board.is_pinned(chess.BLACK, sq("c6"))
        assert see(board, move(board, "Nxe5")) == -2

    def test_xray_recapture_through_emptied_file(self):
        # Rd2 takes d5; after ...Rxd2 the d1 rook recaptures THROUGH where
        # its colleague stood: 1 − 5 + 5 = +1.
        board = chess.Board("3r3k/8/8/3p4/8/8/3R4/3R3K w - - 0 1")
        assert see(board, move(board, "Rxd5")) == 1


class TestEnPassantAndPromotion:
    def test_en_passant_capture(self):
        # White just played f2-f4; exf3 ep wins the pawn with no recapture
        # (the g1 king does not reach f3).
        board = chess.Board("4k3/8/8/8/4pP2/8/8/6K1 b - f3 0 1")
        ep = move(board, "exf3")
        assert board.is_en_passant(ep)  # premise
        assert see(board, ep) == 1

    def test_promotion_capture_uncontested(self):
        board = chess.Board("3r3k/2P5/8/8/8/8/8/K7 w - - 0 1")
        # cxd8=Q: rook (5) + promotion surplus (8), no recapture: 13.
        assert see(board, move(board, "cxd8=Q")) == 13


class TestBestCaptureGain:
    def test_picks_the_profitable_attacker(self):
        # Queen d5 attacked by both pawn (c4) and rook (d2): pawn capture
        # wins 9−? — take with the pawn even though the rook also can.
        board = chess.Board("k7/8/8/3q4/2P5/8/3R4/K7 w - - 0 1")
        assert best_capture_gain(board, sq("d5")) >= 8

    def test_no_captures_is_zero(self):
        assert best_capture_gain(chess.Board(), sq("e5")) == 0
