"""Tag stage tests (Design.md §2, §7 stage 3): schema validation rejects
whole batches, checkable proposals are verified against the board with
contradictions dropped, provenance recorded, three-strikes enforced. The
transport is always a stub — no live LLM in unit tests."""

import json

import pytest
from django.utils import timezone

from games.models import Game
from puzzles.constants import TAG_MAX_ATTEMPTS
from puzzles.models import Occurrence, Puzzle, PuzzleMotif
from puzzles.pipeline.tagging import (
    BatchInvalid,
    build_prompt,
    parse_response,
    run_tag_stage,
    tag_queue,
)

pytestmark = pytest.mark.django_db

# Position after 1.e4 d5 (white to move): exd5 is a genuine winning capture
# premise for hanging-piece... actually Qxd5 recaptures, so hanging-piece
# does NOT fire here — which makes it the perfect contradiction fixture.
FEN = "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2"


@pytest.fixture
def puzzle():
    game = Game.objects.create(
        chesscom_uuid="t-1", url="x", pgn="1. e4 d5", end_time=timezone.now(),
        time_class="blitz", time_control="300", user_color="white",
        user_rating=1500, opponent_username="o", opponent_rating=1500,
        result="loss",
    )
    puzzle = Puzzle.objects.create(
        fen=FEN, position_key="t" * 64, puzzle_type="avoid",
        direction="allowed", win_pct_before=55.0,
        solutions=[{"uci": "e4d5", "san": "exd5", "win_pct": 55.0,
                    "pv_uci": ["e4d5", "d8d5"]}],
        uniqueness_gap_wp=12.0, shallow_depth_stable=True,
        shallow_depth_used=10, cashout_plies=1, phase="middlegame",
        quality_score=1.0,
    )
    Occurrence.objects.create(puzzle=puzzle, game=game, ply=3,
                              played_uci="a2a3", played_san="a3",
                              win_pct_after_played=40.0)
    return puzzle


def response_for(puzzle, tags, explanation="You overlooked the pawn grab."):
    return json.dumps([{"puzzle_id": puzzle.pk, "tags": tags,
                        "explanation": explanation}])


class TestPrompt:
    def test_prompt_contains_the_facts(self, puzzle):
        prompt = build_prompt([puzzle])
        assert FEN in prompt
        assert f"puzzle_id {puzzle.pk}" in prompt
        assert "exd5 Qxd5" in prompt        # solution line in SAN
        assert "instead played: a3" in prompt
        assert "ONLY a JSON array" in prompt


class TestValidation:
    def test_good_payload_passes(self, puzzle):
        text = response_for(puzzle, [{"slug": "zwischenzug", "confidence": 0.8}])
        assert parse_response(text, {puzzle.pk})[0]["puzzle_id"] == puzzle.pk

    def test_prose_around_json_tolerated(self, puzzle):
        text = "Here you go:\n" + response_for(puzzle, []) + "\nHope that helps!"
        assert parse_response(text, {puzzle.pk})

    @pytest.mark.parametrize("bad", [
        "not json at all",
        '{"puzzle_id": 1}',                                      # not a list
        '[{"tags": [], "explanation": "x"}]',                    # id missing
        '[{"puzzle_id": 1, "tags": [], "explanation": ""}]',     # empty expl
        '[{"puzzle_id": 1, "explanation": "x",'
        ' "tags": [{"slug": "brilliancy", "confidence": 1}]}]',
        '[{"puzzle_id": 1, "explanation": "x",'
        ' "tags": [{"slug": "fork", "confidence": 7}]}]',
    ])
    def test_bad_payloads_fail_the_batch(self, bad):
        with pytest.raises(BatchInvalid):
            parse_response(bad.replace('"puzzle_id": 1',
                                       '"puzzle_id": 1'), {1})

    def test_wrong_or_missing_ids_fail(self, puzzle):
        with pytest.raises(BatchInvalid):
            parse_response(response_for(puzzle, []), {puzzle.pk, 99999})


class TestVerifyAndStore:
    def test_uncheckable_tier2_stored_with_null_verification(self, puzzle):
        transport = lambda prompt: response_for(  # noqa: E731
            puzzle, [{"slug": "zwischenzug", "confidence": 0.7}])
        counts = run_tag_stage(transport)
        assert counts["tagged"] == 1 and counts["tags_stored"] == 1
        row = PuzzleMotif.objects.get(puzzle=puzzle, tag__slug="zwischenzug")
        assert row.source == "llm"
        assert row.confidence == 0.7
        assert row.rule_verified is None
        puzzle.refresh_from_db()
        assert puzzle.tagged_at is not None
        assert puzzle.explanation == "You overlooked the pawn grab."
        assert puzzle.explanation_model == "claude-sonnet-5"

    def test_checkable_contradiction_dropped_not_stored(self, puzzle):
        # hanging-piece has a checker; in this position exd5 is met by Qxd5
        # (SEE 0), so the detector refutes the proposal → dropped.
        transport = lambda prompt: response_for(  # noqa: E731
            puzzle, [{"slug": "hanging-piece", "confidence": 0.9}])
        counts = run_tag_stage(transport)
        assert counts["tags_dropped"] == 1 and counts["tags_stored"] == 0
        assert not PuzzleMotif.objects.filter(puzzle=puzzle).exists()
        puzzle.refresh_from_db()
        assert puzzle.tagged_at is not None  # enrichment still succeeded

    def test_checkable_confirmation_stored_verified(self, puzzle):
        # mate-threat's checker is deterministic on mate_in: with mate_in
        # set, the proposal is confirmed → stored as llm + rule_verified.
        puzzle.mate_in = 2
        puzzle.save()
        transport = lambda prompt: response_for(  # noqa: E731
            puzzle, [{"slug": "mate-threat", "confidence": 0.9}])
        counts = run_tag_stage(transport)
        assert counts["tags_stored"] == 1 and counts["tags_dropped"] == 0
        row = PuzzleMotif.objects.get(puzzle=puzzle, tag__slug="mate-threat")
        assert row.source == "llm"
        assert row.rule_verified is True

    def test_existing_rule_tag_not_duplicated(self, puzzle):
        from puzzles.models import MotifTag
        PuzzleMotif.objects.create(
            puzzle=puzzle, tag=MotifTag.objects.get(slug="zwischenzug"),
            source="rule", confidence=1.0, rule_verified=True)
        transport = lambda prompt: response_for(  # noqa: E731
            puzzle, [{"slug": "zwischenzug", "confidence": 0.5}])
        run_tag_stage(transport)
        row = PuzzleMotif.objects.get(puzzle=puzzle, tag__slug="zwischenzug")
        assert row.source == "rule" and row.confidence == 1.0  # rule row kept


class TestThreeStrikes:
    def test_failed_batch_increments_and_requeues(self, puzzle):
        counts = run_tag_stage(lambda prompt: "garbage", max_batches=1)
        assert counts["failed_batches"] == 1
        puzzle.refresh_from_db()
        assert puzzle.tag_attempts == 1
        assert puzzle.tagged_at is None
        assert puzzle in tag_queue()  # still queued (1 < 3)

    def test_three_strikes_skips(self, puzzle):
        puzzle.tag_attempts = TAG_MAX_ATTEMPTS
        puzzle.save()
        counts = run_tag_stage(lambda prompt: pytest.fail("must not be called"))
        assert counts["batches"] == 0
        assert counts["skipped_three_strikes"] == 1

    def test_transport_failure_stops_run_without_striking(self, puzzle):
        # Rate limits and auth failures are not the puzzles' fault: no
        # strike, run stops, the untouched queue retries next cron tick.
        def broken(prompt):
            raise RuntimeError("claude -p failed (1): no auth")
        counts = run_tag_stage(broken)  # would loop forever if it didn't stop
        assert counts["failed_batches"] == 1
        assert "no auth" in counts["stopped_on_transport_error"]
        puzzle.refresh_from_db()
        assert puzzle.tag_attempts == 0
        assert puzzle in tag_queue()
