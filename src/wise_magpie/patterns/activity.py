"""User activity detection for wise-magpie.

Detects whether the user is actively using Claude by checking for running
processes, and records activity sessions in the database.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta

from wise_magpie import db, config, constants
from wise_magpie.models import ActivitySession

# Module-level state: tracks the current open activity session.
_current_session_id: int | None = None


def is_user_active() -> bool:
    """Check if the user is currently using Claude.

    Returns True if any ``claude`` process is found running.
    """
    try:
        result = subprocess.run(
            ["pgrep", "-f", "claude"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # pgrep exits 0 when at least one process matches.
        return result.returncode == 0 and bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def detect_claude_processes() -> list[dict]:
    """Return a list of dicts describing running claude processes.

    Each dict contains ``pid`` (int) and ``cmdline`` (str).
    """
    processes: list[dict] = []
    try:
        pgrep_result = subprocess.run(
            ["pgrep", "-f", "claude"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if pgrep_result.returncode != 0 or not pgrep_result.stdout.strip():
            return processes

        pids = pgrep_result.stdout.strip().splitlines()
        for pid_str in pids:
            pid_str = pid_str.strip()
            if not pid_str:
                continue
            try:
                pid = int(pid_str)
            except ValueError:
                continue

            # Fetch the full command line for this PID.
            try:
                ps_result = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "args="],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                cmdline = ps_result.stdout.strip() if ps_result.returncode == 0 else ""
            except (FileNotFoundError, subprocess.TimeoutExpired):
                cmdline = ""

            processes.append({"pid": pid, "cmdline": cmdline})
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return processes


def record_activity() -> None:
    """Record the current activity state into the database.

    * If the user is active and no session is open, create a new one.
    * If the user is active and a session is already open, update it
      (bump its ``end_time`` to now).
    * If the user is *not* active but a session is open, close it.
    """
    global _current_session_id

    db.init_db()
    active = is_user_active()
    now = datetime.now()

    if active:
        if _current_session_id is None:
            # Start a new session.
            session = ActivitySession(start_time=now, end_time=None, message_count=0)
            _current_session_id = db.insert_activity_session(session)
        else:
            # Keep existing session alive -- update end_time.
            sessions = db.get_recent_sessions(limit=1)
            for s in sessions:
                if s.id == _current_session_id:
                    s.end_time = now
                    s.message_count += 1
                    db.update_activity_session(s)
                    break
    else:
        # User is not active.
        if _current_session_id is not None:
            # Close the open session.
            sessions = db.get_recent_sessions(limit=1)
            for s in sessions:
                if s.id == _current_session_id:
                    s.end_time = now
                    db.update_activity_session(s)
                    break
            _current_session_id = None


def get_idle_minutes() -> float:
    """Return the number of minutes since the last detected activity.

    Looks at the most recent activity session's ``end_time``.  If there are
    no recorded sessions, returns ``float('inf')``.
    """
    db.init_db()
    sessions = db.get_recent_sessions(limit=1)
    if not sessions:
        return float("inf")

    last = sessions[0]
    reference = last.end_time if last.end_time is not None else last.start_time
    delta = datetime.now() - reference
    return max(delta.total_seconds() / 60.0, 0.0)
