"""Tests for auto-task generation."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from wise_magpie import db
from wise_magpie.models import Task, TaskSource, TaskStatus
from wise_magpie.tasks.sources.auto_tasks import (
    BUILTIN_TEMPLATES,
    _branch_commit_count,
    _check_template,
    _has_code_changes_since,
    _has_commits_since,
    _interval_elapsed,
    _last_completed_at,
    _template_map,
    scan,
)


# ---------------------------------------------------------------------------
# Template basics
# ---------------------------------------------------------------------------


def test_builtin_templates_count():
    assert len(BUILTIN_TEMPLATES) == 12


def test_template_map_keys():
    tm = _template_map()
    assert set(tm.keys()) == {
        "run_tests",
        "update_docs",
        "clean_commits",
        "lint_check",
        "dependency_check",
        "security_audit",
        "test_coverage",
        "dead_code_detection",
        "changelog_generation",
        "deprecation_cleanup",
        "type_coverage",
        "pentest_checklist",
    }


def test_all_templates_have_auto_task_type():
    for t in BUILTIN_TEMPLATES:
        assert t.task_type in _template_map()


# ---------------------------------------------------------------------------
# scan() — disabled globally
# ---------------------------------------------------------------------------


def test_scan_disabled_by_default():
    """auto_tasks.enabled defaults to false, so scan should return nothing."""
    with patch("wise_magpie.tasks.sources.auto_tasks.config") as mock_cfg:
        mock_cfg.load_config.return_value = {}
        assert scan("/tmp") == []


def test_scan_disabled_explicitly():
    with patch("wise_magpie.tasks.sources.auto_tasks.config") as mock_cfg:
        mock_cfg.load_config.return_value = {"auto_tasks": {"enabled": False}}
        assert scan("/tmp") == []


# ---------------------------------------------------------------------------
# scan() — enabled, conditions met
# ---------------------------------------------------------------------------


def test_scan_returns_tasks_when_conditions_met():
    """When all conditions pass, scan should produce Task objects."""
    cfg = {
        "auto_tasks": {
            "enabled": True,
            "work_dir": "/tmp/repo",
            "run_tests": {"enabled": True, "interval_hours": 24},
            "update_docs": {"enabled": False},
            "clean_commits": {"enabled": False},
            "lint_check": {"enabled": False},
            "dependency_check": {"enabled": False},
        },
    }

    with (
        patch("wise_magpie.tasks.sources.auto_tasks.config") as mock_cfg,
        patch("wise_magpie.tasks.sources.auto_tasks._check_template") as mock_check,
    ):
        mock_cfg.load_config.return_value = cfg
        # Only run_tests will pass the check
        mock_check.side_effect = lambda t, p, c: t.task_type == "run_tests"

        tasks = scan("/some/path")

    assert len(tasks) == 1
    assert tasks[0].source == TaskSource.AUTO_TASK
    assert tasks[0].source_ref.startswith("run_tests:")
    assert tasks[0].title == "Run test suite"


def test_scan_source_ref_contains_today():
    """source_ref should be '{type}:{YYYY-MM-DD}' using today's date."""
    from datetime import date

    cfg = {"auto_tasks": {"enabled": True}}

    with (
        patch("wise_magpie.tasks.sources.auto_tasks.config") as mock_cfg,
        patch("wise_magpie.tasks.sources.auto_tasks._check_template", return_value=True),
    ):
        mock_cfg.load_config.return_value = cfg
        tasks = scan("/tmp")

    today = date.today().isoformat()
    for t in tasks:
        assert t.source_ref.endswith(f":{today}")


def test_scan_dedup_same_day():
    """Running scan twice on the same day should produce tasks with the same
    source_ref, so the caller's dedup logic in manager.scan_tasks prevents
    duplicates."""
    cfg = {"auto_tasks": {"enabled": True}}

    with (
        patch("wise_magpie.tasks.sources.auto_tasks.config") as mock_cfg,
        patch("wise_magpie.tasks.sources.auto_tasks._check_template", return_value=True),
    ):
        mock_cfg.load_config.return_value = cfg
        first = scan("/tmp")
        second = scan("/tmp")

    first_refs = {t.source_ref for t in first}
    second_refs = {t.source_ref for t in second}
    assert first_refs == second_refs


# ---------------------------------------------------------------------------
# _interval_elapsed
# ---------------------------------------------------------------------------


def test_interval_elapsed_never_completed():
    """If no task of this type was ever completed, interval is elapsed."""
    assert _interval_elapsed("run_tests", 24) is True


def test_interval_elapsed_recently_completed():
    """A task completed 1 hour ago should NOT satisfy a 24-hour interval."""
    completed_task = Task(
        title="Run test suite",
        source=TaskSource.AUTO_TASK,
        source_ref="run_tests:2026-01-01",
        status=TaskStatus.COMPLETED,
        completed_at=datetime.now() - timedelta(hours=1),
    )
    db.insert_task(completed_task)

    assert _interval_elapsed("run_tests", 24) is False


def test_interval_elapsed_old_completion():
    """A task completed 48 hours ago SHOULD satisfy a 24-hour interval."""
    completed_task = Task(
        title="Run test suite",
        source=TaskSource.AUTO_TASK,
        source_ref="run_tests:2026-01-01",
        status=TaskStatus.COMPLETED,
        completed_at=datetime.now() - timedelta(hours=48),
    )
    db.insert_task(completed_task)

    assert _interval_elapsed("run_tests", 24) is True


# ---------------------------------------------------------------------------
# _last_completed_at
# ---------------------------------------------------------------------------


def test_last_completed_at_no_tasks():
    assert _last_completed_at("run_tests") is None


def test_last_completed_at_finds_latest():
    older = Task(
        title="Run test suite",
        source=TaskSource.AUTO_TASK,
        source_ref="run_tests:2026-01-01",
        status=TaskStatus.COMPLETED,
        completed_at=datetime.now() - timedelta(days=5),
    )
    newer = Task(
        title="Run test suite",
        source=TaskSource.AUTO_TASK,
        source_ref="run_tests:2026-01-10",
        status=TaskStatus.COMPLETED,
        completed_at=datetime.now() - timedelta(days=1),
    )
    db.insert_task(older)
    db.insert_task(newer)

    result = _last_completed_at("run_tests")
    assert result is not None
    # Should be the newer one (1 day ago, not 5 days ago)
    assert result > datetime.now() - timedelta(days=2)


# ---------------------------------------------------------------------------
# _check_template — individual template conditions
# ---------------------------------------------------------------------------


def test_check_template_disabled_in_config():
    template = _template_map()["run_tests"]
    cfg = {"run_tests": {"enabled": False}}
    assert _check_template(template, "/tmp", cfg) is False


def test_check_template_interval_not_elapsed():
    """Template should not fire if interval hasn't elapsed."""
    template = _template_map()["dependency_check"]

    # Insert a recently completed dependency_check
    t = Task(
        title="Check dependency updates",
        source=TaskSource.AUTO_TASK,
        source_ref="dependency_check:2026-01-01",
        status=TaskStatus.COMPLETED,
        completed_at=datetime.now() - timedelta(hours=1),
    )
    db.insert_task(t)

    cfg = {"dependency_check": {"enabled": True, "interval_hours": 168}}
    assert _check_template(template, "/tmp", cfg) is False


def test_check_template_clean_commits_below_threshold():
    """clean_commits should not fire when commit count is below threshold."""
    template = _template_map()["clean_commits"]
    cfg = {"clean_commits": {"enabled": True, "min_commits": 10}}

    with patch(
        "wise_magpie.tasks.sources.auto_tasks._branch_commit_count",
        return_value=5,
    ):
        assert _check_template(template, "/tmp", cfg) is False


def test_check_template_clean_commits_above_threshold():
    """clean_commits should fire when commit count >= threshold."""
    template = _template_map()["clean_commits"]
    cfg = {"clean_commits": {"enabled": True, "min_commits": 10}}

    with patch(
        "wise_magpie.tasks.sources.auto_tasks._branch_commit_count",
        return_value=15,
    ):
        assert _check_template(template, "/tmp", cfg) is True


def test_check_template_needs_new_commits_none_found():
    """run_tests requires new commits; should fail if none found."""
    template = _template_map()["run_tests"]
    cfg = {"run_tests": {"enabled": True, "interval_hours": 24}}

    with patch(
        "wise_magpie.tasks.sources.auto_tasks._has_commits_since",
        return_value=False,
    ):
        assert _check_template(template, "/tmp", cfg) is False


def test_check_template_needs_code_changes_none_found():
    """lint_check requires code changes; should fail if none found."""
    template = _template_map()["lint_check"]
    cfg = {"lint_check": {"enabled": True, "interval_hours": 12}}

    with patch(
        "wise_magpie.tasks.sources.auto_tasks._has_code_changes_since",
        return_value=False,
    ):
        assert _check_template(template, "/tmp", cfg) is False


def test_check_template_all_conditions_met():
    """run_tests with interval elapsed and new commits → should fire."""
    template = _template_map()["run_tests"]
    cfg = {"run_tests": {"enabled": True, "interval_hours": 24}}

    with patch(
        "wise_magpie.tasks.sources.auto_tasks._has_commits_since",
        return_value=True,
    ):
        assert _check_template(template, "/tmp", cfg) is True


# ---------------------------------------------------------------------------
# Git helper edge cases (mocked subprocess)
# ---------------------------------------------------------------------------


def test_has_commits_since_success():
    with patch("wise_magpie.tasks.sources.auto_tasks.subprocess") as mock_sub:
        mock_sub.run.return_value.returncode = 0
        mock_sub.run.return_value.stdout = "abc1234 some commit\n"
        assert _has_commits_since("/tmp", datetime.now() - timedelta(hours=24)) is True


def test_has_commits_since_no_commits():
    with patch("wise_magpie.tasks.sources.auto_tasks.subprocess") as mock_sub:
        mock_sub.run.return_value.returncode = 0
        mock_sub.run.return_value.stdout = ""
        assert _has_commits_since("/tmp", datetime.now() - timedelta(hours=24)) is False


def test_has_commits_since_not_a_repo():
    with patch("wise_magpie.tasks.sources.auto_tasks.subprocess") as mock_sub:
        mock_sub.run.return_value.returncode = 128
        mock_sub.run.return_value.stdout = ""
        assert _has_commits_since("/tmp", datetime.now()) is False


def test_has_code_changes_since_success():
    with patch("wise_magpie.tasks.sources.auto_tasks.subprocess") as mock_sub:
        mock_sub.run.return_value.returncode = 0
        mock_sub.run.return_value.stdout = "abc1234 changed file\n"
        assert _has_code_changes_since("/tmp", datetime.now() - timedelta(hours=12)) is True


def test_branch_commit_count_on_main():
    """When already on main, rev-list main..HEAD returns 0."""
    with patch("wise_magpie.tasks.sources.auto_tasks.subprocess") as mock_sub:
        mock_sub.run.return_value.returncode = 0
        mock_sub.run.return_value.stdout = "0\n"
        assert _branch_commit_count("/tmp") == 0


def test_branch_commit_count_no_main_or_master():
    """When neither main nor master exists, return 0."""
    with patch("wise_magpie.tasks.sources.auto_tasks.subprocess") as mock_sub:
        mock_sub.run.return_value.returncode = 128
        mock_sub.run.return_value.stdout = ""
        assert _branch_commit_count("/tmp") == 0


# ---------------------------------------------------------------------------
# Integration: scan produces correct Task fields
# ---------------------------------------------------------------------------


def test_scan_task_fields():
    """Verify that tasks produced by scan() have the expected field values."""
    cfg = {"auto_tasks": {"enabled": True}}

    with (
        patch("wise_magpie.tasks.sources.auto_tasks.config") as mock_cfg,
        patch("wise_magpie.tasks.sources.auto_tasks._check_template", return_value=True),
    ):
        mock_cfg.load_config.return_value = cfg
        tasks = scan("/tmp")

    for t in tasks:
        assert t.source == TaskSource.AUTO_TASK
        assert t.status == TaskStatus.PENDING
        assert t.title != ""
        assert t.description != ""
        assert t.created_at is not None


def test_scan_uses_work_dir_from_config():
    """scan() should use auto_tasks.work_dir when set."""
    cfg = {"auto_tasks": {"enabled": True, "work_dir": "/custom/repo"}}

    calls = []

    def fake_check(template, path, c):
        calls.append(path)
        return False

    with (
        patch("wise_magpie.tasks.sources.auto_tasks.config") as mock_cfg,
        patch("wise_magpie.tasks.sources.auto_tasks._check_template", side_effect=fake_check),
    ):
        mock_cfg.load_config.return_value = cfg
        scan("/ignored/path")

    assert all(p == "/custom/repo" for p in calls)


# ---------------------------------------------------------------------------
# New template condition tests
# ---------------------------------------------------------------------------


def test_check_template_security_audit_needs_code_changes():
    """security_audit requires code changes; should fail if none found."""
    template = _template_map()["security_audit"]
    cfg = {"security_audit": {"enabled": True, "interval_hours": 168}}

    with patch(
        "wise_magpie.tasks.sources.auto_tasks._has_code_changes_since",
        return_value=False,
    ):
        assert _check_template(template, "/tmp", cfg) is False


def test_check_template_security_audit_fires():
    """security_audit with interval elapsed and code changes → should fire."""
    template = _template_map()["security_audit"]
    cfg = {"security_audit": {"enabled": True, "interval_hours": 168}}

    with patch(
        "wise_magpie.tasks.sources.auto_tasks._has_code_changes_since",
        return_value=True,
    ):
        assert _check_template(template, "/tmp", cfg) is True


def test_check_template_test_coverage_needs_code_changes():
    """test_coverage requires code changes; should fail if none found."""
    template = _template_map()["test_coverage"]
    cfg = {"test_coverage": {"enabled": True, "interval_hours": 48}}

    with patch(
        "wise_magpie.tasks.sources.auto_tasks._has_code_changes_since",
        return_value=False,
    ):
        assert _check_template(template, "/tmp", cfg) is False


def test_check_template_test_coverage_fires():
    """test_coverage with interval elapsed and code changes → should fire."""
    template = _template_map()["test_coverage"]
    cfg = {"test_coverage": {"enabled": True, "interval_hours": 48}}

    with patch(
        "wise_magpie.tasks.sources.auto_tasks._has_code_changes_since",
        return_value=True,
    ):
        assert _check_template(template, "/tmp", cfg) is True


def test_check_template_dead_code_detection_needs_code_changes():
    """dead_code_detection requires code changes; should fail if none found."""
    template = _template_map()["dead_code_detection"]
    cfg = {"dead_code_detection": {"enabled": True, "interval_hours": 168}}

    with patch(
        "wise_magpie.tasks.sources.auto_tasks._has_code_changes_since",
        return_value=False,
    ):
        assert _check_template(template, "/tmp", cfg) is False


def test_check_template_changelog_generation_below_threshold():
    """changelog_generation should not fire when commit count is below min_commits."""
    template = _template_map()["changelog_generation"]
    cfg = {"changelog_generation": {"enabled": True, "min_commits": 5}}

    with patch(
        "wise_magpie.tasks.sources.auto_tasks._branch_commit_count",
        return_value=3,
    ):
        assert _check_template(template, "/tmp", cfg) is False


def test_check_template_changelog_generation_above_threshold():
    """changelog_generation should fire when commit count >= min_commits."""
    template = _template_map()["changelog_generation"]
    cfg = {"changelog_generation": {"enabled": True, "min_commits": 5}}

    with patch(
        "wise_magpie.tasks.sources.auto_tasks._branch_commit_count",
        return_value=7,
    ):
        assert _check_template(template, "/tmp", cfg) is True


def test_check_template_deprecation_cleanup_needs_code_changes():
    """deprecation_cleanup requires code changes; should fail if none found."""
    template = _template_map()["deprecation_cleanup"]
    cfg = {"deprecation_cleanup": {"enabled": True, "interval_hours": 336}}

    with patch(
        "wise_magpie.tasks.sources.auto_tasks._has_code_changes_since",
        return_value=False,
    ):
        assert _check_template(template, "/tmp", cfg) is False


def test_check_template_type_coverage_needs_code_changes():
    """type_coverage requires code changes; should fail if none found."""
    template = _template_map()["type_coverage"]
    cfg = {"type_coverage": {"enabled": True, "interval_hours": 168}}

    with patch(
        "wise_magpie.tasks.sources.auto_tasks._has_code_changes_since",
        return_value=False,
    ):
        assert _check_template(template, "/tmp", cfg) is False


def test_check_template_type_coverage_fires():
    """type_coverage with interval elapsed and code changes → should fire."""
    template = _template_map()["type_coverage"]
    cfg = {"type_coverage": {"enabled": True, "interval_hours": 168}}

    with patch(
        "wise_magpie.tasks.sources.auto_tasks._has_code_changes_since",
        return_value=True,
    ):
        assert _check_template(template, "/tmp", cfg) is True


def test_check_template_pentest_checklist_needs_code_changes():
    """pentest_checklist requires code changes; should fail if none found."""
    template = _template_map()["pentest_checklist"]
    cfg = {"pentest_checklist": {"enabled": True, "interval_hours": 720}}

    with patch(
        "wise_magpie.tasks.sources.auto_tasks._has_code_changes_since",
        return_value=False,
    ):
        assert _check_template(template, "/tmp", cfg) is False


def test_check_template_pentest_checklist_fires():
    """pentest_checklist with interval elapsed and code changes → should fire."""
    template = _template_map()["pentest_checklist"]
    cfg = {"pentest_checklist": {"enabled": True, "interval_hours": 720}}

    with patch(
        "wise_magpie.tasks.sources.auto_tasks._has_code_changes_since",
        return_value=True,
    ):
        assert _check_template(template, "/tmp", cfg) is True


def test_check_template_pentest_checklist_disabled():
    """pentest_checklist should not fire when disabled in config."""
    template = _template_map()["pentest_checklist"]
    cfg = {"pentest_checklist": {"enabled": False}}

    assert _check_template(template, "/tmp", cfg) is False
