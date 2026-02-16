"""Tests for SQLite persistence layer."""

from datetime import datetime, timedelta

from wise_magpie import db
from wise_magpie.models import (
    ActivitySession,
    QuotaWindow,
    SchedulePattern,
    Task,
    TaskSource,
    TaskStatus,
    UsageRecord,
)


def test_insert_and_get_task():
    task = Task(title="Test task", description="desc", source=TaskSource.MANUAL)
    task_id = db.insert_task(task)
    assert task_id is not None

    fetched = db.get_task(task_id)
    assert fetched is not None
    assert fetched.title == "Test task"
    assert fetched.status == TaskStatus.PENDING


def test_update_task():
    task = Task(title="Original")
    task.id = db.insert_task(task)
    task.title = "Updated"
    task.status = TaskStatus.RUNNING
    db.update_task(task)

    fetched = db.get_task(task.id)
    assert fetched.title == "Updated"
    assert fetched.status == TaskStatus.RUNNING


def test_delete_task():
    task_id = db.insert_task(Task(title="To delete"))
    assert db.delete_task(task_id) is True
    assert db.get_task(task_id) is None
    assert db.delete_task(999) is False


def test_get_tasks_by_status():
    db.insert_task(Task(title="Pending1"))
    t2 = Task(title="Running1", status=TaskStatus.RUNNING)
    db.insert_task(t2)

    pending = db.get_tasks_by_status(TaskStatus.PENDING)
    assert any(t.title == "Pending1" for t in pending)

    running = db.get_tasks_by_status(TaskStatus.RUNNING)
    assert any(t.title == "Running1" for t in running)


def test_insert_and_get_usage():
    record = UsageRecord(
        timestamp=datetime.now(),
        model="test-model",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.01,
        autonomous=True,
    )
    rid = db.insert_usage(record)
    assert rid is not None

    since = datetime.now() - timedelta(hours=1)
    records = db.get_usage_since(since)
    assert len(records) >= 1
    assert records[-1].model == "test-model"


def test_daily_autonomous_cost():
    record = UsageRecord(
        timestamp=datetime.now(),
        model="test-model",
        cost_usd=1.50,
        autonomous=True,
    )
    db.insert_usage(record)
    cost = db.get_daily_autonomous_cost(datetime.now())
    assert cost >= 1.50


def test_quota_window():
    window = QuotaWindow(
        window_start=datetime.now(),
        window_hours=5,
        estimated_limit=225,
        used_count=10,
    )
    wid = db.insert_quota_window(window)
    assert wid is not None

    current = db.get_current_quota_window()
    assert current is not None
    assert current.estimated_limit == 225

    current.used_count = 20
    db.update_quota_window(current)
    updated = db.get_current_quota_window()
    assert updated.used_count == 20


def test_schedule_patterns():
    pattern = SchedulePattern(
        day_of_week=0, hour=10,
        activity_probability=0.8, avg_usage=5.0, sample_count=10,
    )
    db.upsert_schedule_pattern(pattern)

    patterns = db.get_schedule_patterns()
    assert len(patterns) >= 1
    found = [p for p in patterns if p.day_of_week == 0 and p.hour == 10]
    assert len(found) == 1
    assert found[0].activity_probability == 0.8

    # Upsert should update, not duplicate
    pattern.activity_probability = 0.9
    db.upsert_schedule_pattern(pattern)
    patterns = db.get_schedule_patterns()
    found = [p for p in patterns if p.day_of_week == 0 and p.hour == 10]
    assert len(found) == 1
    assert found[0].activity_probability == 0.9


def test_activity_sessions():
    session = ActivitySession(start_time=datetime.now())
    sid = db.insert_activity_session(session)
    assert sid is not None

    sessions = db.get_recent_sessions(limit=5)
    assert len(sessions) >= 1

    s = sessions[0]
    s.end_time = datetime.now()
    s.message_count = 5
    db.update_activity_session(s)

    updated = db.get_recent_sessions(limit=1)
    assert updated[0].message_count == 5
