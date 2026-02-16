"""Data models for wise-magpie."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime


class TaskStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskSource(enum.Enum):
    MANUAL = "manual"
    GIT_TODO = "git_todo"
    ISSUE = "issue"
    MARKDOWN = "markdown"
    QUEUE_FILE = "queue_file"


@dataclass
class UsageRecord:
    id: int | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    task_id: int | None = None
    autonomous: bool = False


@dataclass
class QuotaWindow:
    id: int | None = None
    window_start: datetime = field(default_factory=datetime.now)
    window_hours: int = 5
    estimated_limit: int = 225
    used_count: int = 0
    user_correction: int | None = None
    corrected_at: datetime | None = None


@dataclass
class Task:
    id: int | None = None
    title: str = ""
    description: str = ""
    source: TaskSource = TaskSource.MANUAL
    source_ref: str = ""  # e.g. file:line, issue URL
    status: TaskStatus = TaskStatus.PENDING
    priority: float = 0.0
    estimated_tokens: int = 0
    work_branch: str = ""
    work_dir: str = ""
    result_summary: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class SchedulePattern:
    day_of_week: int = 0  # 0=Monday
    hour: int = 0
    activity_probability: float = 0.0
    avg_usage: float = 0.0
    sample_count: int = 0


@dataclass
class ActivitySession:
    id: int | None = None
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None
    message_count: int = 0
