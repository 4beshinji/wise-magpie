"""Tests for activity patterns and prediction."""

from datetime import datetime, timedelta
from unittest.mock import patch

from wise_magpie import db
from wise_magpie.models import ActivitySession, SchedulePattern
from wise_magpie.patterns.activity import get_idle_minutes, is_user_active
from wise_magpie.patterns.predictor import predict_idle_windows, predict_next_return, estimate_wasted_quota
from wise_magpie.patterns.schedule import get_pattern, update_patterns


def test_is_user_active_no_corrections():
    """With no quota corrections, user is considered inactive."""
    assert is_user_active() is False


def test_is_user_active_single_correction():
    """With only one correction snapshot, not enough data → inactive."""
    from wise_magpie.models import QuotaWindow

    window = QuotaWindow(window_start=datetime.now(), window_hours=5, estimated_limit=225, used_count=0)
    window.id = db.insert_quota_window(window)
    db.insert_quota_correction(window.id, "claude-sonnet-4-5-20250929", 30, scope="session")
    assert is_user_active() is False


def test_is_user_active_quota_changed():
    """When quota pct changed between syncs, user is active."""
    from wise_magpie.models import QuotaWindow

    window = QuotaWindow(window_start=datetime.now(), window_hours=5, estimated_limit=225, used_count=0)
    window.id = db.insert_quota_window(window)
    db.insert_quota_correction(window.id, "claude-sonnet-4-5-20250929", 30, scope="session")
    db.insert_quota_correction(window.id, "claude-sonnet-4-5-20250929", 35, scope="session")
    assert is_user_active() is True


def test_is_user_active_quota_unchanged():
    """When quota pct is the same between syncs, user is idle."""
    from wise_magpie.models import QuotaWindow

    window = QuotaWindow(window_start=datetime.now(), window_hours=5, estimated_limit=225, used_count=0)
    window.id = db.insert_quota_window(window)
    db.insert_quota_correction(window.id, "claude-sonnet-4-5-20250929", 30, scope="session")
    db.insert_quota_correction(window.id, "claude-sonnet-4-5-20250929", 30, scope="session")
    assert is_user_active() is False


def test_get_idle_minutes_no_sessions():
    idle = get_idle_minutes()
    assert idle == float("inf")


def test_get_idle_minutes_with_session():
    session = ActivitySession(
        start_time=datetime.now() - timedelta(minutes=10),
        end_time=datetime.now() - timedelta(minutes=5),
        message_count=3,
    )
    db.insert_activity_session(session)
    idle = get_idle_minutes()
    assert 4 < idle < 10


def test_update_and_get_patterns():
    # Create a session spanning several hours
    now = datetime.now()
    session = ActivitySession(
        start_time=now - timedelta(hours=3),
        end_time=now - timedelta(hours=1),
        message_count=10,
    )
    db.insert_activity_session(session)

    update_patterns()

    # Should have some patterns now
    patterns = db.get_schedule_patterns()
    assert len(patterns) > 0


def test_get_pattern_missing():
    p = get_pattern(6, 3)
    # May or may not exist depending on test order, but should not crash
    assert p is None or isinstance(p, SchedulePattern)


def test_predict_idle_windows():
    windows = predict_idle_windows(hours_ahead=24)
    assert isinstance(windows, list)
    for w in windows:
        assert "start" in w
        assert "duration_hours" in w
        assert w["duration_hours"] > 0


def test_predict_next_return():
    # With no pattern data, should return None
    result = predict_next_return()
    assert result is None or isinstance(result, datetime)


def test_estimate_wasted_quota():
    waste = estimate_wasted_quota(hours_ahead=24)
    assert "idle_hours" in waste
    assert "wasted_messages" in waste
    assert waste["idle_hours"] >= 0
