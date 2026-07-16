"""
Every tunable threshold in the pipeline, in one module and nowhere else
(Design.md §10). These are defensible defaults, expected to move during the
M4 calibration session — record changes and observations in Design.md §10.
"""

BLUNDER_WP_DROP = 20.0        # win-percentage-point drop => blunder
MISTAKE_WP_DROP = 10.0        # 10–20pp => mistake
SALVAGEABLE_WP_MIN = 25.0     # Gate 1: position must have been worth saving
UNIQUENESS_GAP_WP = 10.0      # Gate 3: best vs best-non-solution
SOLUTION_BAND_WP = 5.0        # moves within this of best join solution set
MAX_SOLUTIONS = 2             # more than this => not a puzzle
SHALLOW_DEPTH = 10            # Gate 2: findability check depth
MULTIPV = 3                   # Gate 3: candidate probe needs top-N moves
CASHOUT_MAX_PLIES = 6         # Gate 2: gain must materialise within this
MATE_MAX_MOVES = 4            # Gate 2: mates must cash out within this
TRIVIAL_MAX_LEGAL_MOVES = 2   # Gate 4: this few legal moves => trivial
BOOK_PLY_CUTOFF = 10          # Gate 4: opening exclusion...
OPENING_LEAK_MIN_GAMES = 3    # ...unless recurring (distinct games, via
                              #    Candidate rows) => opening-leak puzzle
# PUNISH: puzzle exists only if the user's played reply realised LESS than
# this fraction of the win% the opponent's error handed over. (>= fraction
# means they punished adequately — nothing to train.)
PUNISH_CAPTURE_FRACTION = 0.5
CLOCK_COMFORTABLE_MIN_S = 60  # clock buckets (Occurrence.ClockBucket)
CLOCK_SCRAMBLE_MAX_S = 20
PHASE_OPENING_MAX_PLY = 20    # phase classification (context, not gating)
PHASE_ENDGAME_MAX_PIECES = 6  # non-pawn, non-king pieces on the board
NEW_PUZZLES_PER_DAY = 10      # serving: cap on newly introduced puzzles
TAG_MAX_ATTEMPTS = 3          # tag stage three-strikes (poison-pill defence)
