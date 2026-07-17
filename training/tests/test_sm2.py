"""Exhaustive sm2_update tests — every grade path, lapse behaviour, the ease
floor, and multi-review growth. No database, no Django, no clock."""

import pytest

from training.sm2 import Sm2State, derive_grade, sm2_update


class TestGradeDerivation:
    @pytest.mark.parametrize("correct,latency,hints,expected", [
        (False, 1_000, 0, 1),     # fail, however fast
        (False, None, 2, 1),
        (True, 5_000, 1, 3),      # any hint caps at 3
        (True, 5_000, 2, 3),
        (True, 90_000, 0, 4),     # slow
        (True, 30_000, 0, 4),     # boundary: exactly 30 s is not "clean"
        (True, None, 0, 4),       # unknown latency counts as slow
        (True, 29_999, 0, 5),     # clean
        (True, 500, 0, 5),
    ])
    def test_table(self, correct, latency, hints, expected):
        assert derive_grade(correct, latency, hints) == expected


class TestLapse:
    def test_fail_resets_and_penalises(self):
        state = Sm2State(interval_days=42.0, ease_factor=2.5,
                         repetitions=7, lapses=1)
        result = sm2_update(state, correct=False, latency_ms=9_000, hints_used=0)
        assert result.grade == 1
        assert result.state == Sm2State(interval_days=1.0, ease_factor=2.3,
                                        repetitions=0, lapses=2)

    def test_ease_floor(self):
        state = Sm2State(ease_factor=1.35)
        result = sm2_update(state, correct=False, latency_ms=None, hints_used=0)
        assert result.state.ease_factor == 1.3
        again = sm2_update(result.state, correct=False, latency_ms=None,
                           hints_used=0)
        assert again.state.ease_factor == 1.3  # never below the floor


class TestSuccess:
    def test_first_two_intervals_are_fixed(self):
        first = sm2_update(Sm2State(), correct=True, latency_ms=5_000,
                           hints_used=0)
        assert first.state.interval_days == 1.0
        assert first.state.repetitions == 1
        second = sm2_update(first.state, correct=True, latency_ms=5_000,
                            hints_used=0)
        assert second.state.interval_days == 6.0

    def test_third_interval_multiplies_by_ease(self):
        state = Sm2State(interval_days=6.0, ease_factor=2.5, repetitions=2)
        result = sm2_update(state, correct=True, latency_ms=5_000, hints_used=0)
        # grade 5: ease 2.5 + 0.1 = 2.6 → 6 × 2.6 = 15.6
        assert result.state.ease_factor == 2.6
        assert result.state.interval_days == pytest.approx(15.6)

    def test_grade_three_shrinks_ease(self):
        state = Sm2State(ease_factor=2.5)
        result = sm2_update(state, correct=True, latency_ms=5_000, hints_used=1)
        # grade 3: 2.5 + (0.1 − 2×(0.08 + 2×0.02)) = 2.36
        assert result.state.ease_factor == pytest.approx(2.36)

    def test_lapses_carry_through_success(self):
        state = Sm2State(lapses=3)
        result = sm2_update(state, correct=True, latency_ms=1_000, hints_used=0)
        assert result.state.lapses == 3


class TestTrajectories:
    def test_clean_streak_grows_geometrically(self):
        state = Sm2State()
        intervals = []
        for _ in range(6):
            result = sm2_update(state, correct=True, latency_ms=4_000,
                                hints_used=0)
            state = result.state
            intervals.append(state.interval_days)
        from itertools import pairwise
        assert intervals[0] == 1.0 and intervals[1] == 6.0
        assert all(b > a for a, b in pairwise(intervals[1:]))
        assert intervals[-1] > 60  # a mastered puzzle leaves the rotation

    def test_fail_after_streak_returns_tomorrow(self):
        state = Sm2State()
        for _ in range(4):
            state = sm2_update(state, correct=True, latency_ms=4_000,
                               hints_used=0).state
        failed = sm2_update(state, correct=False, latency_ms=4_000,
                            hints_used=0).state
        assert failed.interval_days == 1.0 and failed.repetitions == 0

    def test_purity_no_django(self):
        import training.sm2 as module
        source = open(module.__file__).read()
        assert "django" not in source.lower()
