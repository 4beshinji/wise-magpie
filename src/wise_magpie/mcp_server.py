"""MCP (Model Context Protocol) server for wise-magpie.

Implements the JSON-RPC 2.0 / MCP protocol over stdio using LSP-style
Content-Length framing. No external dependencies beyond the standard library.

Usage (add to ~/.claude/mcp.json):
  {
    "mcpServers": {
      "wise-magpie": {
        "command": "wise-magpie",
        "args": ["mcp", "start"]
      }
    }
  }
"""

from __future__ import annotations

import json
import sys
from typing import Any

from wise_magpie import __version__

# ---------------------------------------------------------------------------
# Protocol helpers
# ---------------------------------------------------------------------------

_PROTOCOL_VERSION = "2024-11-05"


def _read_message() -> dict | None:
    """Read one LSP-framed JSON-RPC message from stdin.

    Returns the parsed dict, or None on EOF.
    """
    # Read headers until blank line
    content_length: int | None = None
    while True:
        raw = sys.stdin.buffer.readline()
        if not raw:
            return None  # EOF
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if line == "":
            break  # end of headers
        if line.lower().startswith("content-length:"):
            content_length = int(line.split(":", 1)[1].strip())

    if content_length is None:
        return None

    body = sys.stdin.buffer.read(content_length)
    return json.loads(body.decode("utf-8"))


def _write_message(obj: dict) -> None:
    """Write one LSP-framed JSON-RPC message to stdout."""
    body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
    sys.stdout.buffer.write(header + body)
    sys.stdout.buffer.flush()


def _ok(request_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

_TOOLS: list[dict] = [
    {
        "name": "enqueue_task",
        "description": (
            "Add a new task to the wise-magpie queue. "
            "The task will be executed autonomously when quota is available."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title for the task.",
                },
                "description": {
                    "type": "string",
                    "description": "Detailed description of what the task should do.",
                },
                "priority": {
                    "type": "number",
                    "description": "Numeric priority (higher = runs sooner). Defaults to auto-calculated.",
                },
                "max_retries": {
                    "type": "integer",
                    "description": "Number of retry attempts on failure. 0 means no retry.",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "list_pending_tasks",
        "description": "List all pending and running tasks in the wise-magpie queue.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_quota_summary",
        "description": "Get the current Claude API quota status and remaining budget.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_task_status",
        "description": "Get detailed status information for a specific task by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The numeric task ID.",
                },
            },
            "required": ["task_id"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _tool_enqueue_task(args: dict) -> str:
    from wise_magpie.tasks.manager import add_task

    title: str = args["title"]
    description: str = args.get("description", "")
    priority: float = float(args.get("priority", 0.0))
    max_retries: int = int(args.get("max_retries", 0))

    task = add_task(
        title=title,
        description=description,
        priority=priority,
        max_retries=max_retries,
    )
    return f"Task #{task.id} added: {title}"


def _tool_list_pending_tasks(_args: dict) -> str:
    from wise_magpie import db
    from wise_magpie.models import TaskStatus

    db.init_db()
    tasks = db.get_tasks_by_status(TaskStatus.PENDING, TaskStatus.RUNNING)

    if not tasks:
        return "No pending or running tasks."

    lines: list[str] = [
        f"{'ID':>4}  {'Status':<10}  {'Pri':>5}  {'Title'}",
        "-" * 60,
    ]
    for t in tasks:
        title_short = t.title if len(t.title) <= 42 else t.title[:39] + "..."
        lines.append(
            f"{t.id or 0:>4}  {t.status.value:<10}  {t.priority:>5.1f}  {title_short}"
        )
    lines.append(f"\n{len(tasks)} task(s).")
    return "\n".join(lines)


def _tool_get_quota_summary(_args: dict) -> str:
    from wise_magpie import constants
    from wise_magpie.quota.estimator import estimate_remaining

    lines: list[str] = ["Quota Summary", "=" * 40]
    for alias in ("opus", "sonnet", "haiku"):
        full_id = constants.MODEL_ALIASES[alias]
        info = estimate_remaining(model=full_id)
        lines.append(
            f"{alias:<8}  limit={info['model_limit']:>4}  "
            f"used={info['used']:>4}  remaining={info['remaining']:>4} "
            f"({info['remaining_pct']:.0f}%)"
        )

    # Default model autonomous budget
    default_info = estimate_remaining()
    lines.append("")
    lines.append(f"Safety reserved:     {default_info['safety_reserved']}")
    lines.append(f"Available for tasks: {default_info['available_for_autonomous']}")
    lines.append(
        f"Window: {default_info['window_start'].strftime('%H:%M')} - "
        f"{default_info['window_end'].strftime('%H:%M')}"
    )
    return "\n".join(lines)


def _tool_get_task_status(args: dict) -> str:
    from wise_magpie import db

    task_id = int(args["task_id"])
    db.init_db()
    task = db.get_task(task_id)

    if task is None:
        return f"Task #{task_id} not found."

    parts: list[str] = [
        f"Task #{task.id}",
        f"  Title:       {task.title}",
        f"  Status:      {task.status.value}",
        f"  Priority:    {task.priority:.1f}",
        f"  Source:      {task.source.value}",
        f"  Model:       {task.model or 'auto'}",
        f"  Max retries: {task.max_retries}",
        f"  Retry count: {task.retry_count}",
        f"  Created:     {task.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    if task.started_at:
        parts.append(f"  Started:     {task.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    if task.completed_at:
        parts.append(f"  Completed:   {task.completed_at.strftime('%Y-%m-%d %H:%M:%S')}")
    if task.description:
        parts.append(f"  Description: {task.description}")
    if task.result_summary:
        parts.append(f"  Result:      {task.result_summary}")
    return "\n".join(parts)


_TOOL_HANDLERS = {
    "enqueue_task": _tool_enqueue_task,
    "list_pending_tasks": _tool_list_pending_tasks,
    "get_quota_summary": _tool_get_quota_summary,
    "get_task_status": _tool_get_task_status,
}


# ---------------------------------------------------------------------------
# Request dispatch
# ---------------------------------------------------------------------------

def _handle_initialize(request_id: Any, _params: dict) -> dict:
    return _ok(
        request_id,
        {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "wise-magpie", "version": __version__},
        },
    )


def _handle_tools_list(request_id: Any, _params: dict) -> dict:
    return _ok(request_id, {"tools": _TOOLS})


def _handle_tools_call(request_id: Any, params: dict) -> dict:
    name: str = params.get("name", "")
    args: dict = params.get("arguments", {}) or {}

    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        return _error(request_id, -32601, f"Unknown tool: {name}")

    try:
        text = handler(args)
    except Exception as exc:  # noqa: BLE001
        return _error(request_id, -32603, f"Tool error: {exc}")

    return _ok(
        request_id,
        {
            "content": [{"type": "text", "text": text}],
            "isError": False,
        },
    )


def _dispatch(message: dict) -> dict | None:
    """Dispatch a single JSON-RPC message and return a response (or None for notifications)."""
    method: str = message.get("method", "")
    request_id: Any = message.get("id")
    params: dict = message.get("params") or {}

    # Notifications have no id – process but do not respond.
    is_notification = "id" not in message

    if method == "initialize":
        response = _handle_initialize(request_id, params)
    elif method == "initialized":
        return None  # notification, no response
    elif method == "tools/list":
        response = _handle_tools_list(request_id, params)
    elif method == "tools/call":
        response = _handle_tools_call(request_id, params)
    elif method == "ping":
        response = _ok(request_id, {})
    else:
        if is_notification:
            return None
        response = _error(request_id, -32601, f"Method not found: {method}")

    return response


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def serve() -> None:
    """Run the MCP server on stdio (blocking)."""
    while True:
        try:
            message = _read_message()
        except Exception:  # noqa: BLE001
            break

        if message is None:
            break  # EOF

        try:
            response = _dispatch(message)
        except Exception as exc:  # noqa: BLE001
            response = _error(message.get("id"), -32603, f"Internal error: {exc}")

        if response is not None:
            _write_message(response)
