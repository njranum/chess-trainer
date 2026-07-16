"""
The engine boundary: centipawns → win-percentage points, engine perspective →
user perspective. Raw engine scores must not escape past this module.

Invariants (Design.md §3):
- All stored win% are from the USER's perspective, always. Engine scores are
  relative to a side; flipping happens here, exactly once.
- Mate scores are not centipawns — the sigmoid never sees them. They clamp
  to 100 (user mates) or 0 (user gets mated).
"""

import math

import chess
import chess.engine

# Lichess's constant for the cp → win% sigmoid.
_WP_SIGMOID_K = 0.00368208


def cp_to_wp(cp: float) -> float:
    """Side-relative centipawns → win% (0–100) for that same side."""
    return 50.0 + 50.0 * (2.0 / (1.0 + math.exp(-_WP_SIGMOID_K * cp)) - 1.0)


def score_to_user_wp(score: chess.engine.PovScore, user_color: chess.Color) -> float:
    """Engine PovScore → win% from the user's perspective.

    Handles the perspective flip (the classic silent-corruption bug: after
    the user's move the side to move is the opponent) and mate clamping.
    """
    pov = score.pov(user_color)
    if pov.is_mate():
        # Total ordering on Score handles MateGiven and mated-in-N uniformly.
        return 100.0 if pov > chess.engine.Cp(0) else 0.0
    cp = pov.score()
    if cp is None:  # engine gave no score at all — should not happen
        raise ValueError(f"unscoreable engine result: {score}")
    return cp_to_wp(cp)
