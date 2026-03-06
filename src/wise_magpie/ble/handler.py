"""Command handler for BLE GATT service.

Dispatches JSON commands received via the Command characteristic to
existing wise-magpie functions and returns JSON responses.

Command format (UTF-8 JSON written to Command characteristic):
    {"cmd": "status"}
    {"cmd": "tasks"}
    {"cmd": "add", "title": "Fix bug", "description": "..."}
    {"cmd": "quota"}

Response format (UTF-8 JSON read/notified from Response characteristic):
    {"ok": true, "data": "..."}
    {"ok": false, "error": "..."}
"""

from __future__ import annotations

import json
from typing import Any


def dispatch(payload: bytes) -> bytes:
    """Parse a JSON command and return a JSON response as bytes."""
    try:
        cmd = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return _error(f"Invalid JSON: {exc}")

    if not isinstance(cmd, dict) or "cmd" not in cmd:
        return _error("Missing 'cmd' field")

    handler = _HANDLERS.get(cmd["cmd"])
    if handler is None:
        return _error(f"Unknown command: {cmd['cmd']}")

    try:
        result = handler(cmd)
        return _ok(result)
    except Exception as exc:  # noqa: BLE001
        return _error(str(exc))


def get_status_snapshot() -> bytes:
    """Return a compact JSON status string for the Status characteristic."""
    try:
        data = _cmd_status({})
        return json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    except Exception:  # noqa: BLE001
        return b'{"daemon":"unknown"}'


# --- Command implementations ------------------------------------------------


def _cmd_status(_cmd: dict) -> dict[str, Any]:
    from wise_magpie import db
    from wise_magpie.config import data_dir
    from wise_magpie.constants import PID_FILE_NAME
    from wise_magpie.models import TaskStatus

    pid_file = data_dir() / PID_FILE_NAME
    daemon_running = pid_file.exists()

    db.init_db()
    pending = len(db.get_tasks_by_status(TaskStatus.PENDING))
    running = len(db.get_tasks_by_status(TaskStatus.RUNNING))

    return {
        "daemon": "running" if daemon_running else "stopped",
        "pending_tasks": pending,
        "running_tasks": running,
    }


def _cmd_tasks(_cmd: dict) -> list[dict[str, Any]]:
    from wise_magpie import db
    from wise_magpie.models import TaskStatus

    db.init_db()
    tasks = db.get_tasks_by_status(TaskStatus.PENDING, TaskStatus.RUNNING)

    return [
        {
            "id": t.id,
            "title": t.title[:60],
            "status": t.status.value,
            "priority": t.priority,
        }
        for t in tasks
    ]


def _cmd_add(cmd: dict) -> dict[str, Any]:
    from wise_magpie.tasks.manager import add_task

    title = cmd.get("title")
    if not title:
        raise ValueError("Missing 'title'")

    task = add_task(
        title=title,
        description=cmd.get("description", ""),
        priority=float(cmd.get("priority", 0.0)),
    )
    return {"task_id": task.id, "title": task.title}


def _cmd_quota(_cmd: dict) -> dict[str, Any]:
    from wise_magpie import constants
    from wise_magpie.quota.estimator import estimate_remaining

    result: dict[str, Any] = {}
    for alias in ("opus", "sonnet", "haiku"):
        full_id = constants.MODEL_ALIASES[alias]
        info = estimate_remaining(model=full_id)
        result[alias] = {
            "limit": info["model_limit"],
            "used": info["used"],
            "remaining": info["remaining"],
            "pct": round(info["remaining_pct"]),
        }
    return result


# --- Helpers -----------------------------------------------------------------

_HANDLERS: dict[str, Any] = {
    "status": _cmd_status,
    "tasks": _cmd_tasks,
    "add": _cmd_add,
    "quota": _cmd_quota,
}


def _ok(data: Any) -> bytes:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False, default=str).encode("utf-8")


def _error(message: str) -> bytes:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False).encode("utf-8")
