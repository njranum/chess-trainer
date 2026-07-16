"""Tier-1 detector tests (Design.md §5). Every fixture position's tactical
premise is verified with python-chess before the detector assertion — no
invented chess facts. Each motif has a fires and a does-not-fire case."""

import chess

from puzzles.pipeline.detectors import (
    DetectionContext,
    classify_direction,
    detect_back_rank,
    detect_counting_error,
    detect_discovered_attack,
    detect_fork,
    detect_hanging_piece,
    detect_mate_threat,
    detect_motifs,
    detect_pin,
    detect_promotion,
    detect_skewer,
    detect_trapped_piece,
)


def ctx_for(fen, solution_san, pv_sans=(), played_san=None, puzzle_type="avoid",
            mate_in=None) -> DetectionContext:
    board = chess.Board(fen)
    solution = board.parse_san(solution_san)
    pv = [solution]
    working = board.copy()
    working.push(solution)
    for san in pv_sans:
        move = working.parse_san(san)
        pv.append(move)
        working.push(move)
    played = board.parse_san(played_san) if played_san else None
    return DetectionContext(board=board, solution=solution, pv=pv,
                            played=played, puzzle_type=puzzle_type,
                            mate_in=mate_in)


class TestHangingPiece:
    def test_fires_on_winning_capture(self):
        ctx = ctx_for("k7/8/8/3p4/8/8/3R4/K7 w - - 0 1", "Rxd5")
        assert not ctx.board.is_attacked_by(chess.BLACK, chess.D5)  # premise
        assert detect_hanging_piece(ctx)

    def test_silent_on_even_trade(self):
        ctx = ctx_for("k7/8/4p3/3r4/8/8/3R4/K7 w - - 0 1", "Rxd5")  # SEE 0
        assert not detect_hanging_piece(ctx)

    def test_silent_on_quiet_move(self):
        ctx = ctx_for(chess.STARTING_FEN, "e4")
        assert not detect_hanging_piece(ctx)


class TestCountingError:
    def test_fires_on_losing_exchange_played(self):
        ctx = ctx_for("k7/8/4p3/3p4/8/8/3R4/K7 w - - 0 1",
                      "Rd1", played_san="Rxd5")  # played SEE = 1−5
        assert detect_counting_error(ctx)

    def test_silent_when_played_quietly(self):
        ctx = ctx_for("k7/8/4p3/3p4/8/8/3R4/K7 w - - 0 1",
                      "Rd1", played_san="Rd3")
        assert not detect_counting_error(ctx)


class TestFork:
    def test_royal_knight_fork(self):
        ctx = ctx_for("r3k3/8/8/1N6/8/8/8/6K1 w - - 0 1", "Nc7+")
        after = ctx.after
        assert after.is_check()  # premise: king attacked...
        assert chess.A8 in after.attacks(chess.C7)  # ...and the rook too
        assert detect_fork(ctx)

    def test_no_fork_on_single_target(self):
        ctx = ctx_for(chess.STARTING_FEN, "Nf3")
        assert not detect_fork(ctx)


class TestPin:
    def test_fires_when_solution_creates_working_pin(self):
        ctx = ctx_for("4k3/8/2n5/8/B7/8/8/4K3 w - - 0 1", "Bb5")
        assert ctx.after.is_pinned(chess.BLACK, chess.C6)  # premise
        assert detect_pin(ctx)

    def test_silent_when_king_off_the_ray(self):
        ctx = ctx_for("3k4/8/2n5/8/B7/8/8/4K3 w - - 0 1", "Bb5")
        assert not ctx.after.is_pinned(chess.BLACK, chess.C6)
        assert not detect_pin(ctx)


class TestSkewer:
    def test_king_skewered_to_rook(self):
        ctx = ctx_for("7r/8/5k2/8/8/8/8/2B1K3 w - - 0 1", "Bb2")
        assert ctx.after.is_check()  # premise: the king is hit first
        assert detect_skewer(ctx)

    def test_no_skewer_when_front_piece_not_forced(self):
        # Front piece is a knight (3) vs bishop attacker (3): it can just sit.
        ctx = ctx_for("7r/8/5n2/8/8/8/8/2B1K3 w - - 0 1", "Bb2")
        assert not detect_skewer(ctx)


class TestDiscoveredAttack:
    FEN = "4k3/4q3/8/8/4N3/8/8/4R1K1 w - - 0 1"

    def test_knight_unmasks_rook_on_queen(self):
        ctx = ctx_for(self.FEN, "Nc5")
        assert chess.E7 not in ctx.board.attacks(chess.E1)  # blocked before
        assert chess.E7 in ctx.after.attacks(chess.E1)      # open after
        assert detect_discovered_attack(ctx)

    def test_silent_when_nothing_unmasked(self):
        ctx = ctx_for(self.FEN, "Kg2")
        assert not detect_discovered_attack(ctx)


class TestBackRank:
    def test_fires_on_back_rank_mate(self):
        ctx = ctx_for("6k1/5ppp/8/8/8/8/5PPP/4R1K1 w - - 0 1",
                      "Re8#", mate_in=1)
        final = ctx.board.copy()
        final.push(ctx.pv[0])
        assert final.is_checkmate()  # premise
        assert detect_back_rank(ctx)

    def test_silent_on_non_back_rank_mate(self):
        # Scholar's mate: king on the back rank but the checker is not.
        fen = chess.Board()
        for san in ("e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6"):
            fen.push_san(san)
        ctx = ctx_for(fen.fen(), "Qxf7#", mate_in=1)
        assert not detect_back_rank(ctx)


class TestTrappedPiece:
    def test_cornered_knight_with_no_safe_flight(self):
        # Bg2 hits the a8 knight; b6/c7 flights are covered by the pawns.
        ctx = ctx_for("n3k3/8/1P6/P7/8/8/8/4KB2 w - - 0 1", "Bg2")
        assert ctx.after.is_attacked_by(chess.WHITE, chess.A8)  # premise
        assert detect_trapped_piece(ctx)

    def test_silent_when_flight_squares_are_safe(self):
        ctx = ctx_for("n3k3/8/8/8/8/8/8/4KB2 w - - 0 1", "Bg2")
        assert not detect_trapped_piece(ctx)


class TestMateThreatAndPromotion:
    def test_mate_threat_is_the_mate_flag(self):
        assert detect_mate_threat(ctx_for(chess.STARTING_FEN, "e4", mate_in=3))
        assert not detect_mate_threat(ctx_for(chess.STARTING_FEN, "e4"))

    def test_promotion_move_fires(self):
        ctx = ctx_for("8/2P5/8/8/8/8/8/K3k3 w - - 0 1", "c8=Q+")
        assert detect_promotion(ctx)

    def test_passed_pawn_push_fires(self):
        ctx = ctx_for("8/8/8/2P5/8/8/8/K3k3 w - - 0 1", "c6")
        assert detect_promotion(ctx)

    def test_ordinary_pawn_move_silent(self):
        assert not detect_promotion(ctx_for(chess.STARTING_FEN, "e4"))


class TestDirectionAndRegistry:
    def test_miscounted_wins(self):
        ctx = ctx_for("k7/8/4p3/3p4/8/8/3R4/K7 w - - 0 1",
                      "Rd1", played_san="Rxd5")
        assert classify_direction(ctx, detect_motifs(ctx)) == "miscounted"

    def test_punish_is_missed(self):
        ctx = ctx_for(chess.STARTING_FEN, "e4", puzzle_type="punish")
        assert classify_direction(ctx, set()) == "missed"

    def test_winning_capture_solution_is_missed(self):
        ctx = ctx_for("k7/8/8/3p4/8/8/3R4/K7 w - - 0 1", "Rxd5")
        assert classify_direction(ctx, detect_motifs(ctx)) == "missed"

    def test_default_is_allowed(self):
        ctx = ctx_for(chess.STARTING_FEN, "e4")
        assert classify_direction(ctx, set()) == "allowed"

    def test_registry_matches_the_seeded_tier1_taxonomy(self):
        from puzzles.pipeline.detectors import DETECTORS
        assert set(DETECTORS) == {
            "hanging-piece", "fork", "pin", "skewer", "discovered-attack",
            "back-rank", "trapped-piece", "counting-error", "mate-threat",
            "promotion",
        }

    def test_detect_motifs_returns_registry_slugs(self):
        from puzzles.pipeline.detectors import DETECTORS
        ctx = ctx_for("r3k3/8/8/1N6/8/8/8/6K1 w - - 0 1", "Nc7+")
        tags = detect_motifs(ctx)
        assert "fork" in tags and tags <= set(DETECTORS)
