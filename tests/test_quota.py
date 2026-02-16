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


def test_apply_correction():
    apply_correction(100)
    est = estimate_remaining()
    assert est["remaining"] <= 100


def test_usage_summary_autonomous():
    record_usage(
        model=constants.DEFAULT_MODEL,
        input_tokens=500,
        output_tokens=200,
        autonomous=True,
    )
    summary = get_usage_summary(hours=1)
    assert summary["autonomous_cost"] > 0
