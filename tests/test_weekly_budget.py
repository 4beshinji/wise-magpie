"""Tests for quota/weekly_budget.py."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from wise_magpie import constants
from wise_magpie.quota.weekly_budget import (
    compute_weekly_parallel_limit,
    get_hours_until_weekly_reset,
    get_weekly_parallel_limit,
    update_weekly_limit,
)


# ---------------------------------------------------------------------------
# get_hours_until_weekly_reset
# ---------------------------------------------------------------------------


class TestGetHoursUntilWeeklyReset:
    def _at(self, weekday: int, hour: int = 0) -> datetime:
        """Return a UTC datetime on the given weekday (0=Mon) and hour."""
        # Find a Monday as anchor (2024-01-01 was a Monday)
        anchor = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        day_offset = (weekday - anchor.weekday()) % 7
        return anchor.replace(hour=hour) + __import__("datetime").timedelta(days=day_offset)

    def test_reset_is_in_future(self):
        with patch("wise_magpie.quota.weekly_budget.datetime") as mock_dt:
            # Simulate Tuesday 12:00 UTC; reset is Monday 00:00 → 6 days away
            mock_dt.now.return_value = datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            hours = get_hours_until_weekly_reset()
        assert hours > 0

    def test_result_is_at_most_one_week(self):
        hours = get_hours_until_weekly_reset()
        assert hours <= 7 * 24 + 1  # allow 1h rounding tolerance


# ---------------------------------------------------------------------------
# compute_weekly_parallel_limit
# ---------------------------------------------------------------------------


class TestComputeWeeklyParallelLimit:
    def test_no_remaining_gives_one(self):
        # Already at 90% → must stop expanding
        assert compute_weekly_parallel_limit(90.0, 0.5, 100.0, 1) == 1

    def test_over_target_gives_one(self):
        assert compute_weekly_parallel_limit(95.0, 0.5, 100.0, 1) == 1

    def test_zero_rate_gives_cap(self):
        assert compute_weekly_parallel_limit(50.0, 0.0, 100.0, 1, cap=10) == 10

    def test_zero_hours_gives_cap(self):
        assert compute_weekly_parallel_limit(50.0, 1.0, 0.0, 1, cap=10) == 10

    def test_simple_case(self):
        # remaining = 90 - 40 = 50%; rate_per_task = 1.0/1 = 1%/h; hours = 50
        # n = 50 / (1.0 × 50) = 1
        result = compute_weekly_parallel_limit(40.0, 1.0, 50.0, 1, cap=10)
        assert result == 1

    def test_high_remaining_many_hours_gives_many(self):
        # remaining = 90%; rate_per_task = 0.1%/h; hours = 10
        # n = 90 / (0.1 × 10) = 90
        result = compute_weekly_parallel_limit(0.0, 0.1, 10.0, 1, cap=10)
        assert result == 10  # capped at 10

    def test_normalised_by_n_running(self):
        # rate = 2%/h observed with 2 tasks → rate_per_task = 1%/h
        # remaining = 50%, hours = 50 → n = 50 / (1 × 50) = 1
        result_2_running = compute_weekly_parallel_limit(40.0, 2.0, 50.0, 2, cap=10)
        # rate = 1%/h with 1 task → same calculation
        result_1_running = compute_weekly_parallel_limit(40.0, 1.0, 50.0, 1, cap=10)
        assert result_2_running == result_1_running

    def test_cap_respected(self):
        result = compute_weekly_parallel_limit(0.0, 0.001, 1.0, 1, cap=5)
        assert result <= 5

    def test_custom_target_pct(self):
        # target = 80%; remaining = 80-50 = 30%; rate_per_task = 1%/h; hours = 10
        # n = 30 / (1 × 10) = 3
        result = compute_weekly_parallel_limit(50.0, 1.0, 10.0, 1, target_pct=80.0, cap=10)
        assert result == 3

    def test_returns_at_least_one(self):
        # Even with very high rate, min is 1
        result = compute_weekly_parallel_limit(89.9, 100.0, 168.0, 1, cap=10)
        assert result >= 1


# ---------------------------------------------------------------------------
# update_weekly_limit (integration-style with mocks)
# ---------------------------------------------------------------------------


class TestUpdateWeeklyLimit:
    def _reset_state(self):
        """Reset module-level state between tests."""
        import wise_magpie.quota.weekly_budget as wb
        wb._last_week_pct = None
        wb._last_checked_at = None
        wb._last_n_running = 1
        wb._weekly_parallel_limit = constants.MAX_PARALLEL_TASKS

    def test_no_snapshot_returns_current_limit(self):
        self._reset_state()
        with patch("wise_magpie.quota.weekly_budget.fetch_usage", return_value=None):
            result = update_weekly_limit()
        assert result == constants.MAX_PARALLEL_TASKS

    def test_first_call_no_rate_returns_initial_limit(self):
        self._reset_state()
        snapshot = {"week_all_pct": 30.0, "week_sonnet_pct": None, "five_hour_pct": 0.0,
                    "five_hour_resets_at": None}
        with patch("wise_magpie.quota.weekly_budget.fetch_usage", return_value=snapshot):
            with patch("wise_magpie.quota.weekly_budget.get_hours_until_weekly_reset",
                       return_value=100.0):
                result = update_weekly_limit()
        # First call → no delta → returns WEEKLY_INITIAL_PARALLEL_LIMIT, not the hard cap
        assert result == constants.WEEKLY_INITIAL_PARALLEL_LIMIT

    def test_second_call_computes_limit(self):
        self._reset_state()
        import wise_magpie.quota.weekly_budget as wb

        # Prime state: 30% used, measured 30 min ago
        wb._last_week_pct = 28.0
        wb._last_checked_at = datetime(2024, 1, 2, 11, 30, tzinfo=timezone.utc)
        wb._last_n_running = 2

        snapshot = {"week_all_pct": 30.0, "week_sonnet_pct": None, "five_hour_pct": 0.0,
                    "five_hour_resets_at": None}

        fixed_now = datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc)

        with patch("wise_magpie.quota.weekly_budget.fetch_usage", return_value=snapshot):
            with patch("wise_magpie.quota.weekly_budget.get_hours_until_weekly_reset",
                       return_value=120.0):
                with patch("wise_magpie.quota.weekly_budget.datetime") as mock_dt:
                    mock_dt.now.return_value = fixed_now
                    with patch("wise_magpie.quota.weekly_budget.db") as mock_db:
                        mock_db.get_tasks_by_status.return_value = []
                        result = update_weekly_limit()

        # delta_pct = 2% over 0.5h → rate = 4%/h; n_running was 2 → rate_per_task = 2%/h
        # remaining = 90-30 = 60%; n = 60 / (2 × 120) = 0.25 → 1 (floored) but capped to 1
        assert result >= 1
        assert result <= constants.MAX_PARALLEL_TASKS

    def test_limit_capped_at_max(self):
        self._reset_state()
        import wise_magpie.quota.weekly_budget as wb

        # Very slow rate: almost no consumption
        wb._last_week_pct = 10.0
        wb._last_checked_at = datetime(2024, 1, 2, 11, 30, tzinfo=timezone.utc)
        wb._last_n_running = 1

        snapshot = {"week_all_pct": 10.01, "week_sonnet_pct": None,
                    "five_hour_pct": 0.0, "five_hour_resets_at": None}
        fixed_now = datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc)

        with patch("wise_magpie.quota.weekly_budget.fetch_usage", return_value=snapshot):
            with patch("wise_magpie.quota.weekly_budget.get_hours_until_weekly_reset",
                       return_value=10.0):
                with patch("wise_magpie.quota.weekly_budget.datetime") as mock_dt:
                    mock_dt.now.return_value = fixed_now
                    with patch("wise_magpie.quota.weekly_budget.db") as mock_db:
                        mock_db.get_tasks_by_status.return_value = []
                        result = update_weekly_limit()
        assert result <= constants.MAX_PARALLEL_TASKS


# ---------------------------------------------------------------------------
# get_weekly_parallel_limit (module state accessor)
# ---------------------------------------------------------------------------


class TestGetWeeklyParallelLimit:
    def test_returns_int(self):
        limit = get_weekly_parallel_limit()
        assert isinstance(limit, int)
        assert limit >= 1
