"""User activity detection for wise-magpie.

Detects whether the user is actively using Claude by monitoring quota
variation.  If the usage percentage reported by auto-sync has changed
between the two most recent snapshots, the user is considered active.

Additionally supports direct event injection via Claude Code Hooks:
  wise-magpie activity ping          # called from Notification hook
  wise-magpie activity session-end   # called from Stop hook
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta

from wise_magpie import db, config, constants
from wise_magpie.models import ActivitySession

# Module-level state: tracks the current open activity session.
_current_session_id: int | None = None

# Timestamp of the most recent direct hook ping (bypasses quota-diff check).
_last_hook_ping: datetime | None = None

# Seconds to keep considering "active" after a hook ping with no follow-up.
_HOOK_ACTIVE_WINDOW = 300  # 5 minutes


def hook_ping() -> None:
    """Record a direct activity ping from a Claude Code Hook.

    Call this from a ``Notification`` hook to give wise-magpie an
    authoritative signal that the user is currently active.  The signal
    stays effective for ``_HOOK_ACTIVE_WINDOW`` seconds.
    """
    global _last_hook_ping, _current_session_id

    _last_hook_ping = datetime.now()
    db.init_db()

    now = datetime.now()
    if _current_session_id is None:
        session = ActivitySession(start_time=now, end_time=None, message_count=0)
        _current_session_id = db.insert_activity_session(session)
    else:
        sessions = db.get_recent_sessions(limit=1)
        for s in sessions:
            if s.id == _current_session_id:
                s.end_time = now
                s.message_count += 1
                db.update_activity_session(s)
                break


def hook_session_end() -> None:
    """Record a session-end event from a Claude Code Stop hook.

    Closes the current activity session immediately so the daemon knows
    the user has finished and idle time begins now.
    """
    global _last_hook_ping, _current_session_id

    _last_hook_ping = None
    db.init_db()

    now = datetime.now()
    if _current_session_id is not None:
        sessions = db.get_recent_sessions(limit=1)
        for s in sessions:
            if s.id == _current_session_id:
                s.end_time = now
                db.update_activity_session(s)
                break
        _current_session_id = None


def is_user_active() -> bool:
    """Check if the user is currently using Claude.

    Returns ``True`` if a direct Hook ping was received recently
    (within ``_HOOK_ACTIVE_WINDOW`` seconds).  Falls back to comparing
    the two most recent session-scope quota corrections recorded by
    auto-sync: if the usage percentage changed between them, the user is
    actively consuming quota.  When fewer than two snapshots exist,
    returns ``False`` (not enough data to confirm activity).
    """
    # Hook-based detection takes priority: it is authoritative and immediate.
    if _last_hook_ping is not None:
        elapsed = (datetime.now() - _last_hook_ping).total_seconds()
        if elapsed < _HOOK_ACTIVE_WINDOW:
            return True

    db.init_db()
    corrections = db.get_latest_session_corrections(limit=2)
    if len(corrections) < 2:
        return False
    return corrections[0]["pct_used"] != corrections[1]["pct_used"]


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
