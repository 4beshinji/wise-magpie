"""Tests for data models."""

from wise_magpie.models import Task, TaskSource, TaskStatus, UsageRecord, QuotaWindow


def test_task_defaults():
    t = Task(title="test")
    assert t.status == TaskStatus.PENDING
    assert t.source == TaskSource.MANUAL
    assert t.priority == 0.0
    assert t.id is None


def test_task_status_values():
    assert TaskStatus.PENDING.value == "pending"
    assert TaskStatus.RUNNING.value == "running"
    assert TaskStatus.COMPLETED.value == "completed"


def test_usage_record_defaults():
    r = UsageRecord()
    assert r.cost_usd == 0.0
    assert r.autonomous is False
    assert r.task_id is None
