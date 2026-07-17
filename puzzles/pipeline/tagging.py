"""
Tier-2 tagging + explanations (Design.md §2, §5, §7 stage 3).

LLM output is a proposal, not a fact:
1. schema-validate the whole batch (malformed ⇒ the batch fails, every
   puzzle in it self-requeues via tagged_at IS NULL, tag_attempts += 1);
2. verify any proposed tag that has a deterministic checker against the
   board (Tier-1 detectors) — contradictions are dropped, not stored;
3. store survivors with provenance (source=llm, confidence, rule_verified
   True for checker-confirmed, NULL for uncheckable Tier-2 tags);
4. set tagged_at only on success — tags + explanation are one enrichment.

Three strikes (TAG_MAX_ATTEMPTS) keeps one schema-breaking puzzle from
re-queueing its batch forever.
"""

import json
import re
import subprocess

import chess
from django.db.models import F
from django.utils import timezone

from puzzles.constants import TAG_MAX_ATTEMPTS
from puzzles.models import MotifTag, Puzzle, PuzzleMotif
from puzzles.pipeline.detectors import DETECTORS, DetectionContext

BATCH_SIZE = 12

PROMPT_HEADER = """\
You are annotating chess puzzles mined from one player's own games. For each
puzzle below, do two things:

1. Propose applicable motif tags from this fixed list (and no other):
   deflection, zwischenzug, king-safety, other,
   hanging-piece, fork, pin, skewer, discovered-attack, back-rank,
   trapped-piece, counting-error, mate-threat, promotion
   Only propose a tag you are confident applies. Prefer the first four
   (the rule engine already handles the rest); propose "other" only when a
   clear motif fits nothing listed.

2. Write ONE short sentence (UK English) explaining the key point — why the
   solution works or what the played move overlooked. Plain, coach-like,
   concrete ("your knight was the only defender of f2"), no engine-speak.

Respond with ONLY a JSON array, no prose, one object per puzzle:
[{"puzzle_id": <int>, "tags": [{"slug": "<slug>", "confidence": <0..1>}],
  "explanation": "<one sentence>"}]

Puzzles:
"""

VALID_SLUGS = frozenset((
    "deflection", "zwischenzug", "king-safety", "other",
    "hanging-piece", "fork", "pin", "skewer", "discovered-attack",
    "back-rank", "trapped-piece", "counting-error", "mate-threat", "promotion",
))


class BatchInvalid(Exception):
    """The LLM response failed schema validation — fail the whole batch."""


def tag_queue():
    """Puzzles awaiting enrichment, oldest first, three-strikes excluded."""
    return (Puzzle.objects
            .filter(tagged_at__isnull=True,
                    tag_attempts__lt=TAG_MAX_ATTEMPTS)
            .order_by("created_at"))


def build_prompt(puzzles) -> str:
    blocks = []
    for puzzle in puzzles:
        solution = puzzle.solutions[0]
        pv = solution.get("pv_uci") or [solution["uci"]]
        occurrence = puzzle.occurrences.select_related("game").first()
        played = occurrence.played_san if occurrence else "?"
        rule_tags = ", ".join(puzzle.motifs.values_list("slug", flat=True)) or "none"
        blocks.append(
            f"- puzzle_id {puzzle.pk}: FEN {puzzle.fen}\n"
            f"  solution line: {' '.join(_line_san(puzzle.fen, pv))}\n"
            f"  the player instead played: {played}\n"
            f"  rule-detected tags so far: {rule_tags}\n"
            f"  puzzle type: {puzzle.puzzle_type}"
        )
    return PROMPT_HEADER + "\n".join(blocks)


def parse_response(text: str, expected_ids: set[int]) -> list[dict]:
    """Strict schema validation. Any deviation fails the batch."""
    match = re.search(r"\[.*\]", text, re.DOTALL)  # tolerate stray prose only
    if match is None:
        raise BatchInvalid("no JSON array in response")
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise BatchInvalid(f"unparseable JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise BatchInvalid("top level is not a list")

    seen = set()
    for entry in payload:
        if not isinstance(entry, dict):
            raise BatchInvalid("entry is not an object")
        if not isinstance(entry.get("puzzle_id"), int):
            raise BatchInvalid("puzzle_id missing or not an int")
        if entry["puzzle_id"] not in expected_ids:
            raise BatchInvalid(f"unknown puzzle_id {entry['puzzle_id']}")
        if not isinstance(entry.get("explanation"), str) or not entry["explanation"].strip():
            raise BatchInvalid("explanation missing or empty")
        if not isinstance(entry.get("tags"), list):
            raise BatchInvalid("tags missing or not a list")
        for tag in entry["tags"]:
            if not isinstance(tag, dict) or tag.get("slug") not in VALID_SLUGS:
                raise BatchInvalid(f"invalid tag entry: {tag!r}")
            confidence = tag.get("confidence")
            if not isinstance(confidence, int | float) or not 0 <= confidence <= 1:
                raise BatchInvalid(f"confidence out of range: {tag!r}")
        seen.add(entry["puzzle_id"])
    if seen != expected_ids:
        raise BatchInvalid(f"response covers {seen}, expected {expected_ids}")
    return payload


def apply_entry(puzzle: Puzzle, entry: dict, model_name: str) -> dict:
    """Verify-and-store for one puzzle. Returns counts for reporting."""
    counts = {"stored": 0, "dropped": 0, "duplicate": 0}
    ctx = _detection_context(puzzle)
    for proposal in entry["tags"]:
        slug = proposal["slug"]
        checker = DETECTORS.get(slug)
        rule_verified = None
        if checker is not None:
            if not checker(ctx):
                counts["dropped"] += 1  # contradiction: dropped, not stored
                continue
            rule_verified = True
        tag = MotifTag.objects.get(slug=slug)
        _, created = PuzzleMotif.objects.get_or_create(
            puzzle=puzzle, tag=tag,
            defaults={"source": PuzzleMotif.Source.LLM,
                      "confidence": float(proposal["confidence"]),
                      "rule_verified": rule_verified},
        )
        counts["stored" if created else "duplicate"] += 1

    puzzle.explanation = entry["explanation"].strip()
    puzzle.explanation_model = model_name
    puzzle.tagged_at = timezone.now()
    puzzle.save(update_fields=["explanation", "explanation_model", "tagged_at"])
    return counts


def run_tag_stage(transport, model_name="claude-sonnet-5",
                  max_batches: int | None = None) -> dict:
    """The whole stage: batch, call, validate, verify, store."""
    counts = {"tagged": 0, "batches": 0, "failed_batches": 0,
              "tags_stored": 0, "tags_dropped": 0,
              "skipped_three_strikes": Puzzle.objects.filter(
                  tagged_at__isnull=True,
                  tag_attempts__gte=TAG_MAX_ATTEMPTS).count()}
    while True:
        if max_batches is not None and counts["batches"] >= max_batches:
            break
        batch = list(tag_queue()[:BATCH_SIZE])
        if not batch:
            break
        counts["batches"] += 1
        ids = {p.pk for p in batch}
        try:
            entries = parse_response(transport(build_prompt(batch)), ids)
        except BatchInvalid as exc:
            # Content failure — the poison-pill case three-strikes exists for.
            counts["failed_batches"] += 1
            Puzzle.objects.filter(pk__in=ids).update(
                tag_attempts=F("tag_attempts") + 1)
            counts.setdefault("last_error", str(exc)[:200])
            continue
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            # Transport failure (auth, rate limit, timeout) — not the
            # puzzles' fault; no strike, stop the run and let the next cron
            # tick retry the untouched queue.
            counts["failed_batches"] += 1
            counts["stopped_on_transport_error"] = str(exc)[:200]
            break
        by_id = {e["puzzle_id"]: e for e in entries}
        for puzzle in batch:
            entry_counts = apply_entry(puzzle, by_id[puzzle.pk], model_name)
            counts["tagged"] += 1
            counts["tags_stored"] += entry_counts["stored"]
            counts["tags_dropped"] += entry_counts["dropped"]
    return counts


def _detection_context(puzzle) -> DetectionContext:
    board = chess.Board(puzzle.fen)
    solution = puzzle.solutions[0]
    pv = [chess.Move.from_uci(u)
          for u in (solution.get("pv_uci") or [solution["uci"]])]
    occurrence = puzzle.occurrences.first()
    played = (chess.Move.from_uci(occurrence.played_uci)
              if occurrence else None)
    return DetectionContext(board=board, solution=pv[0], pv=pv, played=played,
                            puzzle_type=puzzle.puzzle_type,
                            mate_in=puzzle.mate_in)


def _line_san(fen: str, pv_uci: list[str]) -> list[str]:
    board = chess.Board(fen)
    sans = []
    for uci in pv_uci:
        move = chess.Move.from_uci(uci)
        sans.append(board.san(move))
        board.push(move)
    return sans
