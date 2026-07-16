"""Ingest stage: idempotency is the whole contract (Design.md §7)."""

import json
import pathlib

import pytest

from games.models import Game, PipelineRun
from games.pipeline.ingest import ingest_games
from games.pipeline.runs import pipeline_run

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.django_db


class FakeClient:
    username = "snoopy"

    def months_to_fetch(self, since):
        return [(2026, 6)]

    def month_games(self, year, month):
        return json.loads((FIXTURES / "month_2026_06.json").read_text())["games"]


def test_ingest_creates_then_updates():
    counts = ingest_games(FakeClient())
    assert counts == {"months": 1, "seen": 4, "created": 3, "updated": 0, "skipped": 1}
    assert Game.objects.count() == 3
    assert set(Game.objects.values_list("analysis_status", flat=True)) == {"pending"}

    # Second run: pure no-op on rows — the idempotency contract.
    counts = ingest_games(FakeClient())
    assert counts["created"] == 0 and counts["updated"] == 3
    assert Game.objects.count() == 3


def test_reingest_does_not_touch_analysis_bookkeeping():
    ingest_games(FakeClient())
    game = Game.objects.get(chesscom_uuid="uuid-a")
    game.analysis_status = Game.AnalysisStatus.ANALYZED
    game.save()
    ingest_games(FakeClient())
    game.refresh_from_db()
    assert game.analysis_status == Game.AnalysisStatus.ANALYZED


def test_pipeline_run_success_and_failure():
    with pipeline_run("ingest") as run:
        run.counts = {"games": 1}
    run.refresh_from_db()
    assert run.status == PipelineRun.Status.SUCCEEDED
    assert run.finished_at is not None

    with pytest.raises(RuntimeError):
        with pipeline_run("ingest"):
            raise RuntimeError("boom")
    failed = PipelineRun.objects.order_by("-started_at").first()
    assert failed.status == PipelineRun.Status.FAILED
    assert "boom" in failed.error_text
