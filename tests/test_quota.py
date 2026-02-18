"""Tests for quota tracking, estimation, and corrections."""

from datetime import datetime

from wise_magpie import constants, db
from wise_magpie.quota.tracker import get_usage_summary, record_usage
from wise_magpie.quota.estimator import estimate_remaining, has_budget_for_task
from wise_magpie.quota.corrections import apply_correction


def test_record_usage():
    rid = record_usage(
        model=constants.DEFAULT_MODEL,
        input_tokens=1000,
        output_tokens=500,
    )
    assert rid is not None

    summary = get_usage_summary(hours=1)
    assert summary["request_count"] >= 1
    assert summary["total_input_tokens"] >= 1000
    assert summary["total_cost"] > 0


def test_record_usage_unknown_model():
    """Unknown model should fall back to default model costs."""
    rid = record_usage(model="unknown-model", input_tokens=100, output_tokens=50)
    assert rid is not None


def test_estimate_remaining():
    est = estimate_remaining()
    assert "remaining" in est
    assert "estimated_limit" in est
    assert "available_for_autonomous" in est
    assert est["remaining"] <= est["estimated_limit"]
    assert est["remaining_pct"] >= 0


def test_has_budget_for_task():
    # Should have budget with fresh state
    assert has_budget_for_task(0.0) is True


def test_apply_correction_session():
    """Session percentage should reduce estimated remaining."""
    apply_correction(session=50)  # 50% used
    est = estimate_remaining()
    limit = est["estimated_limit"]
    # remaining should be roughly half the limit (minus any post-correction usage)
    assert est["remaining"] <= limit // 2 + 1


def test_apply_correction_session_full():
    """100% session usage should yield 0 remaining."""
    apply_correction(session=100)
    est = estimate_remaining()
    assert est["remaining"] == 0


def test_apply_correction_session_zero():
    """0% session usage should yield full remaining."""
    apply_correction(session=0)
    est = estimate_remaining()
    assert est["remaining"] == est["estimated_limit"]


def test_apply_correction_weekly_stored():
    """Week corrections should be retrievable via get_latest_weekly_corrections."""
    apply_correction(week_all=28, week_sonnet=4)
    from wise_magpie import db
    weekly = db.get_latest_weekly_corrections()
    assert weekly["week_all"] is not None
    assert weekly["week_all"]["pct_used"] == 28
    assert weekly["week_sonnet"] is not None
    assert weekly["week_sonnet"]["pct_used"] == 4


def test_apply_correction_no_args_noop(capsys):
    """Calling apply_correction() with no args should print an error and not crash."""
    apply_correction()
    captured = capsys.readouterr()
    assert "No values provided" in captured.err


def test_apply_correction_independent():
    """Weekly corrections should not affect window remaining estimate."""
    est_before = estimate_remaining()
    apply_correction(week_all=90)
    est_after = estimate_remaining()
    assert est_before["remaining"] == est_after["remaining"]


def test_usage_summary_autonomous():
    record_usage(
        model=constants.DEFAULT_MODEL,
        input_tokens=500,
        output_tokens=200,
        autonomous=True,
    )
    summary = get_usage_summary(hours=1)
    assert summary["autonomous_cost"] > 0
