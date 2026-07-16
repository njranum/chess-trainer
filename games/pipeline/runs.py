"""PipelineRun bookkeeping — every stage runs inside one of these
(Design.md §7 failure visibility)."""

import traceback
from contextlib import contextmanager

from django.utils import timezone

from games.models import PipelineRun


@contextmanager
def pipeline_run(stage: str):
    """Wraps a stage: RUNNING row on entry; SUCCEEDED with counts on clean
    exit; FAILED with the traceback on exception (which re-raises)."""
    run = PipelineRun.objects.create(stage=stage)
    try:
        yield run
    except Exception:
        run.status = PipelineRun.Status.FAILED
        run.error_text = traceback.format_exc()
        raise
    else:
        run.status = PipelineRun.Status.SUCCEEDED
    finally:
        run.finished_at = timezone.now()
        run.save()
