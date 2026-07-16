"""
Puzzle extraction core (Design.md §4–6).

Schema invariants (from the design review — see docs/Design.md §6):
- A Puzzle is identified by its normalized position (position_key) alone,
  NOT by game and NOT by solution set (solutions are a deterministic
  function of the position given an engine regime; keying on them would let
  engine noise mint near-duplicates). The same mistake made in five games is
  ONE puzzle with N Occurrences — the occurrence count drives "ones I do
  often". Solutions freeze at first analysis; deeper re-analysis may
  overwrite engine facts, occurrences always accumulate.
- Every gate-evaluated moment persists as a Candidate row, puzzle or not —
  recalibration is a query over Candidates (both tightening AND loosening),
  rejected moments feed stats, and opening-leak promotion counts over them.
- ALL stored win% values are from the USER's perspective, always (see
  puzzles/pipeline/evals.py — the only conversion point).
- Engine facts (win% before, solution set) live on Puzzle; per-game facts
  (what you played, the clock, which game) live on Occurrence.
- Motif tags carry provenance (rule vs LLM) and verification status, so the
  propose-verify tagging step is visible in the data, not just the pipeline.
- Scheduling (SM-2) lives on Puzzle for single-user simplicity. If this ever
  goes multi-user, extract those fields into a ReviewState(user, puzzle)
  model — nothing else changes.
- Portable across SQLite (dev) and Postgres (Lightsail): JSONField
  everywhere, no ArrayField.
"""

from django.db import models

from games.models import Game


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
        constraints = [
            models.UniqueConstraint(fields=["game", "ply"],
                                    name="unique_candidate_per_game_ply"),
        ]

    def __str__(self):
        return f"g{self.game_id} ply {self.ply} ({self.verdict})"


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

    class Phase(models.TextChoices):
        OPENING = "opening"
        MIDDLEGAME = "middlegame"
        ENDGAME = "endgame"

    # Identity
    fen = models.CharField(max_length=100)
    # Normalised dedup key from puzzles/pipeline/positions.py: piece
    # placement + side to move + castling + legal-only ep, counters stripped,
    # hashed for a compact unique index.
    position_key = models.CharField(max_length=64, unique=True)

    # On collision (same position, both types across games): PUNISH wins.
    puzzle_type = models.CharField(max_length=6, choices=PuzzleType.choices)
    direction = models.CharField(max_length=10, choices=Direction.choices)

    # Engine facts about the position (occurrence-independent).
    # All win% are USER-perspective (module docstring).
    win_pct_before = models.FloatField()      # user's win% if best is played
    solutions = models.JSONField()
    #   Each accepted solution carries ITS OWN principal variation — a user
    #   opening with solution #2 still needs a line to play out
    #   (<= MAX_SOLUTIONS entries):
    #   [{"uci": "e4f6", "san": "Nxf6+", "win_pct": 78.2,
    #     "pv_uci": ["e4f6", "g7f6", "d1h5"]}, ...]
    #   Move checking compares UCI; SAN is display-only.
    uniqueness_gap_wp = models.FloatField()   # Gate 3 margin, kept for re-filtering
    shallow_depth_stable = models.BooleanField()       # Gate 2 evidence...
    shallow_depth_used = models.PositiveSmallIntegerField()  # ...and its probe depth
    cashout_plies = models.PositiveSmallIntegerField()  # Gate 2 evidence
    mate_in = models.PositiveSmallIntegerField(null=True, blank=True)

    # Engine provenance — the regime that produced the facts above (Game
    # keeps its own copy; a mixed shallow-backfill/deep history must be
    # distinguishable per puzzle). Overwritten only by deeper re-analysis.
    engine_version = models.CharField(max_length=40, blank=True)
    engine_movetime_ms = models.PositiveIntegerField(null=True, blank=True)

    # Classification / display
    phase = models.CharField(max_length=10, choices=Phase.choices)
    is_opening_leak = models.BooleanField(default=False)
    quality_score = models.FloatField(db_index=True)   # ranking, not gating;
    #   recomputed whenever an occurrence is added (swing = max over occurrences)
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

    def __str__(self):
        return f"{self.get_puzzle_type_display()} [{self.phase}] q={self.quality_score:.2f}"

    @property
    def occurrence_count(self):
        # Recurrence = distinct GAMES — repetitions within one game (e.g.
        # threefold shuffling) must not inflate it.
        return self.occurrences.values("game").distinct().count()


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
    # after your move — flipped at the evals.py boundary, never here)
    win_pct_after_played = models.FloatField()        # => wp drop is derivable
    clock_seconds = models.FloatField(null=True, blank=True)
    # "" = unknown (no %clk in the PGN) — absence is handled, never fabricated
    clock_bucket = models.CharField(max_length=12, choices=ClockBucket.choices,
                                    blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["game", "ply"],
                                    name="unique_occurrence_per_game_ply"),
        ]

    def __str__(self):
        return f"puzzle {self.puzzle_id} in g{self.game_id} ply {self.ply}"

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
        constraints = [
            models.UniqueConstraint(fields=["puzzle", "tag"],
                                    name="unique_motif_per_puzzle"),
        ]

    def __str__(self):
        return f"{self.tag} on puzzle {self.puzzle_id} ({self.source})"
