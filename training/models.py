"""Training attempts + operational feedback (Design.md §8)."""

from django.db import models

from puzzles.models import Puzzle


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

    def __str__(self):
        outcome = "✓" if self.correct else "✗"
        return f"puzzle {self.puzzle_id} {outcome} grade {self.grade}"


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

    def __str__(self):
        state = "resolved" if self.resolved_at else "open"
        return f"report on puzzle {self.puzzle_id} ({state})"
