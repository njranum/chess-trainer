"""
Chess trainer — core data model.

Design notes baked into this schema:
- A Puzzle is identified by its normalized position (position_key) alone,
  NOT by game and NOT by solution set (solutions are a deterministic
  function of the position given an engine regime; keying on them would let
  engine noise mint near-duplicates). The same mistake made in five games is
  ONE puzzle with five Occurrences — the occurrence count drives "ones I do
  often". Solutions freeze at first analysis; deeper re-analysis may
  overwrite engine facts, occurrences always accumulate.
- Every gate-evaluated moment persists as a Candidate row, puzzle or not —
  recalibration is a query over Candidates (both tightening AND loosening),
  rejected moments feed stats, and opening-leak promotion counts over them.
- ALL stored win% values are from the USER's perspective, always. Flip
  side-to-move engine scores when the opponent moves; mate scores clamp to
  100/0 (they are not centipawns — the sigmoid never sees them).
- Engine facts (win% before, solution set) live on Puzzle; per-game facts
  (what you played, the clock, which game) live on Occurrence.
- Motif tags carry provenance (rule vs LLM) and verification status, so the
  propose-verify tagging step is visible in the data, not just the pipeline.
- Scheduling (SM-2) lives on Puzzle for single-user simplicity. If this ever
  goes multi-user, extract those five fields into a ReviewState(user, puzzle)
  model — nothing else changes.
- Portable across SQLite (dev) and Postgres (Lightsail): JSONField everywhere,
  no ArrayField.
"""

from django.db import models

# ---------------------------------------------------------------------------
# Tunable constants — the "design constants" from the filter spec.
# Keep them here (or a constants.py) so calibration is a one-file affair.
# ---------------------------------------------------------------------------

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
TRIVIAL_MAX_LEGAL_MOVES = 2   # Gate 4: fewer legal moves than this => trivial
BOOK_PLY_CUTOFF = 10          # Gate 4: opening exclusion...
OPENING_LEAK_MIN_GAMES = 3    # ...unless recurring (distinct games, via
                              #    Candidate rows) => opening-leak puzzle
# PUNISH: puzzle exists only if the user's played reply realised LESS than
# this fraction of the win% the opponent's error handed over. (>= fraction
# means they punished adequately — nothing to train.)
PUNISH_CAPTURE_FRACTION = 0.5
CLOCK_COMFORTABLE_MIN_S = 60  # clock buckets (Occurrence.ClockBucket)
CLOCK_SCRAMBLE_MAX_S = 20
NEW_PUZZLES_PER_DAY = 10      # serving: cap on newly introduced puzzles
TAG_MAX_ATTEMPTS = 3          # tag stage three-strikes (poison-pill defence)


class TimeClass(models.TextChoices):
    BULLET = "bullet"
    BLITZ = "blitz"
    RAPID = "rapid"
    DAILY = "daily"


class Game(models.Model):
    """One chess.com game, plus the engine-analysis bookkeeping for it."""

    # Identity / provenance
    chesscom_uuid = models.CharField(max_length=64, unique=True)
    url = models.URLField()
    pgn = models.TextField()
    end_time = models.DateTimeField(db_index=True)

    # Game facts
    time_class = models.CharField(max_length=10, choices=TimeClass.choices)
    time_control = models.CharField(max_length=20)          # e.g. "600+5"
    rated = models.BooleanField(default=True)
    user_color = models.CharField(max_length=5)             # "white"/"black"
    user_rating = models.PositiveIntegerField()
    opponent_username = models.CharField(max_length=50)     # shown in serving
    opponent_rating = models.PositiveIntegerField()
    result = models.CharField(max_length=10)                # "win"/"loss"/"draw"
    eco = models.CharField(max_length=3, blank=True)        # e.g. "C50"
    opening_name = models.CharField(max_length=120, blank=True)

    # Analysis bookkeeping — reproducibility matters when you re-tune constants
    class AnalysisStatus(models.TextChoices):
        PENDING = "pending"
        ANALYZED = "analyzed"
        FAILED = "failed"

    analysis_status = models.CharField(
        max_length=10, choices=AnalysisStatus.choices,
        default=AnalysisStatus.PENDING, db_index=True,
    )
    engine_version = models.CharField(max_length=40, blank=True)   # "stockfish 16.1"
    engine_movetime_ms = models.PositiveIntegerField(null=True, blank=True)
    pipeline_version = models.CharField(max_length=20, blank=True) # your extractor version
    ingested_at = models.DateTimeField(auto_now_add=True)
    analyzed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-end_time"]

    def __str__(self):
        return f"{self.end_time:%Y-%m-%d} vs {self.opponent_rating} ({self.result})"


class MotifTag(models.Model):
    """The 13-tag mechanism taxonomy (+ OTHER). Seeded by a data migration."""

    class Tier(models.IntegerChoices):
        RULE = 1      # deterministically detectable
        FUZZY = 2     # LLM-proposed

    slug = models.SlugField(unique=True)      # "hanging-piece", "zwischenzug"
    name = models.CharField(max_length=60)
    tier = models.IntegerField(choices=Tier.choices)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Candidate(models.Model):
    """
    One gate-evaluated moment — the gate ledger. Written for EVERY candidate
    the analyze stage examines, accepted or rejected, so that:
    - recalibration is a query over this table in both directions (loosening
      a constant resurrects rejected rows without re-running the engine);
    - rejected moments still count in game-side stats;
    - opening-leak promotion can see the first two occurrences of a book
      mistake when the third arrives.
    All win% fields are user-perspective (see module docstring).
    """

    class Verdict(models.TextChoices):
        ACCEPTED = "accepted"           # became / joined a Puzzle
        REJECTED = "rejected"           # failed a gate — see rejection_gate

    game = models.ForeignKey(Game, on_delete=models.CASCADE,
                             related_name="candidates")
    ply = models.PositiveIntegerField()
    position_key = models.CharField(max_length=64, db_index=True)
    fen = models.CharField(max_length=100)
    candidate_type = models.CharField(max_length=6)   # Puzzle.PuzzleType values
    played_uci = models.CharField(max_length=6)
    played_san = models.CharField(max_length=10)
    win_pct_before = models.FloatField()
    win_pct_after_played = models.FloatField()
    clock_seconds = models.FloatField(null=True, blank=True)

    # Gate evidence — persisted whether or not the gate passed
    uniqueness_gap_wp = models.FloatField(null=True, blank=True)
    shallow_depth_stable = models.BooleanField(null=True)
    shallow_depth_used = models.PositiveSmallIntegerField(null=True, blank=True)
    cashout_plies = models.PositiveSmallIntegerField(null=True, blank=True)
    legal_move_count = models.PositiveSmallIntegerField(null=True, blank=True)

    verdict = models.CharField(max_length=8, choices=Verdict.choices)
    rejection_gate = models.PositiveSmallIntegerField(null=True, blank=True)
    puzzle = models.ForeignKey("Puzzle", on_delete=models.SET_NULL,
                               null=True, blank=True,
                               related_name="candidates")

    class Meta:
        unique_together = [("game", "ply")]


class Puzzle(models.Model):
    """A unique position extracted from the user's games (see module
    docstring for the identity and collision rules)."""

    class PuzzleType(models.TextChoices):
        AVOID = "avoid"     # position before YOUR error — find the right move
        PUNISH = "punish"   # opponent just erred — find the refutation

    class Direction(models.TextChoices):
        MISSED = "missed"           # a tactic for you existed; you didn't play it
        ALLOWED = "allowed"         # you enabled a tactic against yourself
        MISCOUNTED = "miscounted"   # capture sequence came out negative

    # Identity
    fen = models.CharField(max_length=100)
    # Normalised dedup key: piece placement + side to move + castling + ep
    # (i.e. FEN minus the move counters), hashed for a compact unique index.
    # Normalise ep too: keep the ep square only when a legal ep capture
    # exists (board.epd(en_passant="legal")-style) — a vestigial ep square
    # after any double push makes identical positions hash differently.
    position_key = models.CharField(max_length=64, unique=True)

    # On collision (same position, both types across games): PUNISH wins.
    puzzle_type = models.CharField(max_length=6, choices=PuzzleType.choices)
    direction = models.CharField(max_length=10, choices=Direction.choices)

    # Engine facts about the position (occurrence-independent).
    # All win% are USER-perspective (module docstring).
    win_pct_before = models.FloatField()      # user's win% if best is played
    solutions = models.JSONField()
    #   Each accepted solution carries ITS OWN principal variation — a user
    #   opening with solution #2 still needs a line to play out (<= MAX_SOLUTIONS):
    #   [{"uci": "e4f6", "san": "Nxf6+", "win_pct": 78.2,
    #     "pv_uci": ["e4f6", "g7f6", "d1h5"]}, ...]
    #   Move checking compares UCI; SAN is display-only.
    uniqueness_gap_wp = models.FloatField()   # Gate 3 margin, kept for re-filtering
    shallow_depth_stable = models.BooleanField()       # Gate 2 evidence...
    shallow_depth_used = models.PositiveSmallIntegerField()  # ...and its probe depth
    cashout_plies = models.PositiveSmallIntegerField() # Gate 2 evidence
    mate_in = models.PositiveSmallIntegerField(null=True, blank=True)

    # Engine provenance — the regime that produced the facts above (Game
    # keeps its own copy; a mixed shallow-backfill/deep history must be
    # distinguishable per puzzle). Overwritten only by deeper re-analysis.
    engine_version = models.CharField(max_length=40, blank=True)
    engine_movetime_ms = models.PositiveIntegerField(null=True, blank=True)

    # Classification / display
    phase = models.CharField(
        max_length=10,
        choices=[("opening", "opening"), ("middlegame", "middlegame"),
                 ("endgame", "endgame")],
    )
    is_opening_leak = models.BooleanField(default=False)
    quality_score = models.FloatField(db_index=True)   # ranking, not gating
    motifs = models.ManyToManyField(MotifTag, through="PuzzleMotif", blank=True)

    # LLM enrichment (nullable — app must work without it). tagged_at covers
    # tags + explanation jointly (one enrichment, one timestamp). tag_attempts
    # is the three-strikes counter: skip after TAG_MAX_ATTEMPTS so one
    # schema-breaking puzzle can't re-queue its batch forever.
    explanation = models.TextField(blank=True)         # one-sentence coach note
    explanation_model = models.CharField(max_length=60, blank=True)
    tagged_at = models.DateTimeField(null=True, blank=True)
    tag_attempts = models.PositiveSmallIntegerField(default=0)

    # Spaced repetition (SM-2). Extract to ReviewState if ever multi-user.
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    interval_days = models.FloatField(default=0)
    ease_factor = models.FloatField(default=2.5)
    repetitions = models.PositiveIntegerField(default=0)
    lapses = models.PositiveIntegerField(default=0)

    # Operational: "bury" skips a puzzle without touching SM-2 state or stats.
    buried_until = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["puzzle_type", "phase"]),
            models.Index(fields=["due_at", "-quality_score"]),  # the serving query
        ]

    @property
    def occurrence_count(self):
        # Recurrence = distinct GAMES — repetitions within one game (e.g.
        # threefold shuffling) must not inflate it.
        return self.occurrences.values("game").distinct().count()

    def __str__(self):
        return f"{self.get_puzzle_type_display()} [{self.phase}] q={self.quality_score:.2f}"


class Occurrence(models.Model):
    """One real moment in one real game where this puzzle's position arose."""

    class ClockBucket(models.TextChoices):
        COMFORTABLE = "comfortable"   # > CLOCK_COMFORTABLE_MIN_S
        LOW = "low"                   # between the two edges
        SCRAMBLE = "scramble"         # < CLOCK_SCRAMBLE_MAX_S

    puzzle = models.ForeignKey(Puzzle, on_delete=models.CASCADE,
                               related_name="occurrences")
    game = models.ForeignKey(Game, on_delete=models.CASCADE,
                             related_name="occurrences")
    ply = models.PositiveIntegerField()               # half-move number in game
    played_uci = models.CharField(max_length=6)       # what you actually did
    played_san = models.CharField(max_length=10)
    # User-perspective (raw engine score here is side-to-move = OPPONENT
    # after your move — must be flipped at the boundary or wp_drop is garbage)
    win_pct_after_played = models.FloatField()        # => wp drop is derivable
    clock_seconds = models.FloatField(null=True, blank=True)
    clock_bucket = models.CharField(max_length=12, choices=ClockBucket.choices,
                                    null=True, blank=True)

    class Meta:
        unique_together = [("game", "ply")]

    @property
    def wp_drop(self):
        return self.puzzle.win_pct_before - self.win_pct_after_played


class PuzzleMotif(models.Model):
    """Tag assignment with provenance — the propose-verify trail."""

    class Source(models.TextChoices):
        RULE = "rule"     # Tier 1 detector
        LLM = "llm"       # Tier 2 proposal

    puzzle = models.ForeignKey(Puzzle, on_delete=models.CASCADE)
    tag = models.ForeignKey(MotifTag, on_delete=models.CASCADE)
    source = models.CharField(max_length=4, choices=Source.choices)
    confidence = models.FloatField(default=1.0)       # 1.0 for RULE
    rule_verified = models.BooleanField(null=True)
    # RULE rows: True by construction. LLM rows: True if a checker exists,
    # was run, and agreed; NULL for Tier-2 tags with no checker. False never
    # exists — contradicted proposals are dropped, not stored (invariant).

    class Meta:
        unique_together = [("puzzle", "tag")]


class Attempt(models.Model):
    """
    One training attempt at one puzzle — the whole line, not one move
    (serving is stateless: the client resubmits the full move list, the
    server replays it from the FEN). Feeds SM-2 and all dashboards.
    """

    puzzle = models.ForeignKey(Puzzle, on_delete=models.CASCADE,
                               related_name="attempts")
    moves = models.JSONField(default=list)
    #   The user's moves in order, with per-move verdicts — this is also the
    #   near-miss log that decides whether the tolerance band ever ships:
    #   [{"uci": "e4f6", "verdict": "solution" | "pv" | "near_miss" | "wrong"}, ...]
    correct = models.BooleanField()
    failed_at_ply = models.PositiveSmallIntegerField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    hints_used = models.PositiveSmallIntegerField(default=0)  # 0–2 (two-stage)
    grade = models.PositiveSmallIntegerField()  # derived SM-2 quality 0–5,
    #   stored so scheduling decisions are auditable after the fact
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class WeaknessSnapshot(models.Model):
    """
    Nightly per-motif rollup so the dashboard can show trends over time
    without recomputing history. Everything here is derivable from
    Occurrence/Attempt — this is a cache, and can be rebuilt from scratch.
    """
    date = models.DateField()
    tag = models.ForeignKey(MotifTag, on_delete=models.CASCADE)
    # From your GAMES (are you still making this mistake?)
    occurrences_in_window = models.PositiveIntegerField()   # e.g. trailing 30d
    games_in_window = models.PositiveIntegerField()
    # From your TRAINING (are you solving it when drilled?)
    attempts = models.PositiveIntegerField()
    correct = models.PositiveIntegerField()

    class Meta:
        unique_together = [("date", "tag")]


class PipelineRun(models.Model):
    """One row per stage per run — the pipeline-health page's data source."""

    class Status(models.TextChoices):
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"

    stage = models.CharField(max_length=20)   # "ingest"/"analyze"/"tag"/"snapshot"
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.RUNNING)
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    counts = models.JSONField(default=dict)   # e.g. {"games": 12, "puzzles": 31,
                                              #       "tag_skipped": 1}
    error_text = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]


class Report(models.Model):
    """An unfair-puzzle flag from the train UI — the post-launch calibration
    signal (the ongoing version of the step-4 eyeball session)."""

    puzzle = models.ForeignKey(Puzzle, on_delete=models.CASCADE,
                               related_name="reports")
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
