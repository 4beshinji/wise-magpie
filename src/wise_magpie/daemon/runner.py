"""Main daemon loop and lifecycle management."""

from __future__ import annotations

import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

import click

from wise_magpie import config, constants, db
from wise_magpie.daemon.scheduler import should_execute
from wise_magpie.daemon.signals import SignalHandler
from wise_magpie.models import Task, TaskStatus
from wise_magpie.patterns.activity import record_activity
from wise_magpie.tasks.manager import get_next_task
from wise_magpie.tasks.model_selector import select_model
from wise_magpie.worker.executor import execute_task
from wise_magpie.worker.monitor import check_budget_available, get_task_budget, report_execution
from wise_magpie.worker.sandbox import cleanup_sandbox, create_sandbox

logger = logging.getLogger("wise-magpie")


def _pid_file() -> Path:
    return config.data_dir() / constants.PID_FILE_NAME


def _log_file() -> Path:
    return config.data_dir() / constants.LOG_FILE_NAME


def _setup_logging(foreground: bool) -> None:
    log_file = _log_file()
    handlers: list[logging.Handler] = [logging.FileHandler(str(log_file))]
    if foreground:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )


def _is_running() -> int | None:
    """Check if daemon is running. Returns PID if running, None otherwise."""
    pid_file = _pid_file()
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)  # Check if process exists
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        pid_file.unlink(missing_ok=True)
        return None


def _write_pid() -> None:
    _pid_file().write_text(str(os.getpid()))


def _remove_pid() -> None:
    _pid_file().unlink(missing_ok=True)


def _run_single_task(task: Task) -> None:
    """Execute a single task with sandbox isolation."""
    db.init_db()

    # Select model
    selected_model = select_model(task)
    task.model = selected_model

    task.status = TaskStatus.RUNNING
    task.started_at = datetime.now()
    db.update_task(task)
    logger.info(f"Starting task #{task.id}: {task.title} (model: {selected_model})")

    # Determine work directory (use current dir if not specified)
    work_dir = task.work_dir or os.getcwd()
    sandbox_ctx = None

    try:
        # Create sandbox branch if in a git repo
        git_dir = Path(work_dir) / ".git"
        if git_dir.exists():
            sandbox_ctx = create_sandbox(task.id, task.title, work_dir)  # type: ignore[arg-type]
            task.work_branch = sandbox_ctx.branch_name
            db.update_task(task)
            logger.info(f"  Created branch: {sandbox_ctx.branch_name}")

        # Build prompt
        prompt = (
            f"Task: {task.title}\n"
            f"Description: {task.description}\n\n"
            "Please complete this task. Make all necessary code changes and "
            "commit your work with a descriptive message."
        )

        # Execute
        budget = get_task_budget()
        result = execute_task(
            prompt=prompt,
            work_dir=work_dir,
            task_id=task.id,
            max_budget_usd=budget,
            model=selected_model,
        )

        if result.success:
            task.status = TaskStatus.COMPLETED
            task.result_summary = result.output[:2000]  # Truncate for DB
            logger.info(f"  Task #{task.id} completed successfully")
        else:
            task.status = TaskStatus.FAILED
            task.result_summary = f"Error: {result.error}"
            logger.warning(f"  Task #{task.id} failed: {result.error}")

        task.completed_at = datetime.now()
        db.update_task(task)

        report_execution(
            task.id, result.cost_usd,  # type: ignore[arg-type]
            result.input_tokens + result.output_tokens,
            result.duration_seconds,
        )

    except Exception as e:
        task.status = TaskStatus.FAILED
        task.result_summary = f"Exception: {e}"
        task.completed_at = datetime.now()
        db.update_task(task)
        logger.exception(f"  Task #{task.id} raised exception")
    finally:
        # Return to original branch (keep the work branch for review)
        if sandbox_ctx:
            try:
                cleanup_sandbox(sandbox_ctx, keep_branch=True)
            except Exception:
                logger.exception("Failed to cleanup sandbox")


def _daemon_loop(handler: SignalHandler) -> None:
    """Main daemon loop."""
    db.init_db()
    cfg = config.load_config()
    poll_interval = cfg.get("daemon", {}).get("poll_interval", constants.POLL_INTERVAL_SECONDS)

    logger.info("Daemon started (PID %d)", os.getpid())

    while not handler.should_stop:
        try:
            # Record activity state
            record_activity()

            # Check if we should execute
            should_run, reason = should_execute()

            if should_run:
                task = get_next_task()
                if task:
                    logger.info(f"Scheduling task: {reason}")
                    _run_single_task(task)
                else:
                    logger.debug("should_execute=True but no task available")
            else:
                logger.debug(f"Not executing: {reason}")

        except Exception:
            logger.exception("Error in daemon loop")

        # Wait for next poll or shutdown signal
        handler.wait(poll_interval)

    logger.info("Daemon shutting down")


def start_daemon(foreground: bool) -> None:
    """Start the wise-magpie daemon."""
    existing = _is_running()
    if existing:
        click.echo(f"Daemon already running (PID {existing})")
        raise SystemExit(1)

    db.init_db()
    _setup_logging(foreground)

    if foreground:
        click.echo("Starting wise-magpie daemon in foreground...")
        _write_pid()
        handler = SignalHandler()
        handler.install()
        try:
            _daemon_loop(handler)
        finally:
            _remove_pid()
    else:
        # Fork to background
        pid = os.fork()
        if pid > 0:
            click.echo(f"Daemon started (PID {pid})")
            click.echo(f"Log: {_log_file()}")
            return

        # Child process
        os.setsid()
        # Redirect stdio
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        os.close(devnull)

        _write_pid()
        handler = SignalHandler()
        handler.install()
        try:
            _daemon_loop(handler)
        finally:
            _remove_pid()


def stop_daemon() -> None:
    """Stop the wise-magpie daemon."""
    pid = _is_running()
    if pid is None:
        click.echo("Daemon is not running")
        return

    os.kill(pid, signal.SIGTERM)
    click.echo(f"Sent SIGTERM to daemon (PID {pid})")

    # Wait briefly for clean shutdown
    import time
    for _ in range(10):
        if _is_running() is None:
            click.echo("Daemon stopped")
            return
        time.sleep(0.5)
    click.echo("Daemon may still be shutting down")


def show_status() -> None:
    """Show current status of daemon, quota, and tasks."""
    db.init_db()

    # Daemon status
    pid = _is_running()
    if pid:
        click.echo(f"Daemon:  running (PID {pid})")
    else:
        click.echo("Daemon:  stopped")

    # Quota status
    from wise_magpie.quota.estimator import estimate_remaining
    try:
        est = estimate_remaining()
        click.echo(
            f"Quota:   {est['remaining']}/{est['estimated_limit']} remaining "
            f"({est['remaining_pct']:.0f}%)"
        )
        click.echo(f"         {est['available_for_autonomous']} available for autonomous use")
    except Exception:
        click.echo("Quota:   no data yet")

    # Task status
    running = db.get_tasks_by_status(TaskStatus.RUNNING)
    pending = db.get_tasks_by_status(TaskStatus.PENDING)
    completed = db.get_tasks_by_status(TaskStatus.COMPLETED)

    click.echo(f"Tasks:   {len(running)} running, {len(pending)} pending, {len(completed)} completed")
    if running:
        for t in running:
            click.echo(f"         > #{t.id}: {t.title}")

    # Activity
    from wise_magpie.patterns.activity import get_idle_minutes, is_user_active
    if is_user_active():
        click.echo("Activity: user active")
    else:
        idle = get_idle_minutes()
        click.echo(f"Activity: idle ({idle:.0f}m)")
