"""
SM-2 scheduling as a pure function (Design.md §8; CLAUDE.md invariant).

sm2_update(state, correct, latency_ms, hints_used) → Sm2Result. It takes
state + attempt facts, returns new state, touches nothing — the one piece
of logic whose bugs silently corrupt months of scheduling, so it lives
alone with exhaustive unit tests.

Grading is derived, not self-reported:
- fail                       → grade 1: lapse (repetitions reset, interval
                               1 day, ease −0.2 floored at 1.3)
- success with any hint      → grade 3
- success, slow (or unknown) → grade 4
- success, clean and fast    → grade 5
"""

from dataclasses import dataclass

from puzzles.constants import (
    SM2_CLEAN_LATENCY_MS,
    SM2_LAPSE_EASE_PENALTY,
    SM2_MIN_EASE,
)


@dataclass(frozen=True)
class Sm2State:
    interval_days: float = 0.0
    ease_factor: float = 2.5
    repetitions: int = 0
    lapses: int = 0


@dataclass(frozen=True)
class Sm2Result:
    state: Sm2State
    grade: int          # derived 1–5, stored on the Attempt for auditability


def derive_grade(correct: bool, latency_ms: int | None, hints_used: int) -> int:
    if not correct:
        return 1
    if hints_used > 0:
        return 3
    if latency_ms is None or latency_ms >= SM2_CLEAN_LATENCY_MS:
        return 4
    return 5


def sm2_update(state: Sm2State, correct: bool, latency_ms: int | None,
               hints_used: int) -> Sm2Result:
    grade = derive_grade(correct, latency_ms, hints_used)

    if grade < 3:  # lapse
        return Sm2Result(
            state=Sm2State(
                interval_days=1.0,
                ease_factor=max(SM2_MIN_EASE,
                                state.ease_factor - SM2_LAPSE_EASE_PENALTY),
                repetitions=0,
                lapses=state.lapses + 1,
            ),
            grade=grade,
        )

    # Standard SM-2 ease adjustment for successful recall.
    ease = state.ease_factor + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
    ease = max(SM2_MIN_EASE, ease)
    repetitions = state.repetitions + 1
    if repetitions == 1:
        interval = 1.0
    elif repetitions == 2:
        interval = 6.0
    else:
        interval = round(state.interval_days * ease, 1)

    return Sm2Result(
        state=Sm2State(interval_days=interval, ease_factor=round(ease, 4),
                       repetitions=repetitions, lapses=state.lapses),
        grade=grade,
    )
