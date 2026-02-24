"""Anthropic Message Batches API integration.

Submits pending tasks in bulk to the Batch API for 50% cost reduction.
Results are available within 24 hours.

Batch API reference:
  POST https://api.anthropic.com/v1/messages/batches
  GET  https://api.anthropic.com/v1/messages/batches/{batch_id}
  GET  https://api.anthropic.com/v1/messages/batches/{batch_id}/results
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from wise_magpie import constants
from wise_magpie import db
from wise_magpie.models import Task, TaskStatus

_CREDENTIALS_FILE = Path.home() / ".claude" / ".credentials.json"
_BATCH_BASE_URL = "https://api.anthropic.com/v1/messages/batches"
_ANTHROPIC_VERSION = "2023-06-01"
_BATCH_BETA = "message-batches-2024-09-24"
_DEFAULT_MAX_TOKENS = 4096
_DEFAULT_MODEL = constants.DEFAULT_MODEL


def _get_api_key() -> str | None:
    """Read the Anthropic API key from ~/.claude/.credentials.json."""
    try:
        data = json.loads(_CREDENTIALS_FILE.read_text())
        # Try direct apiKey field first, then nested paths
        api_key = data.get("apiKey") or data.get("api_key")
        if api_key:
            return api_key
        # Some credential files store it under claudeAiOauth or similar
        oauth = data.get("claudeAiOauth") or {}
        return oauth.get("apiKey") or oauth.get("api_key") or None
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def _build_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": _ANTHROPIC_VERSION,
        "anthropic-beta": _BATCH_BETA,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _resolve_model(model: str | None) -> str:
    """Resolve a model alias or return the default model."""
    if not model:
        # Check config for batch-specific model, fall back to global default
        try:
            from wise_magpie import config
            cfg_model = config.get("batch", "model", None)
        except Exception:
            cfg_model = None
        model = cfg_model or _DEFAULT_MODEL
    return constants.resolve_model(model)


def _task_to_batch_request(task: Task, model: str) -> dict[str, Any]:
    """Convert a Task to a Batch API request object."""
    # Build the prompt from title + description
    content = task.title
    if task.description:
        content = f"{task.title}\n\n{task.description}"

    return {
        "custom_id": str(task.id),
        "params": {
            "model": model,
            "max_tokens": _DEFAULT_MAX_TOKENS,
            "messages": [
                {"role": "user", "content": content},
            ],
        },
    }


def submit_batch(tasks: list[Task], model: str | None = None) -> str | None:
    """Submit a list of tasks to the Anthropic Batch API.

    Args:
        tasks: Tasks to submit. Each task's title/description becomes the prompt.
        model: Model alias or full ID. Defaults to batch config or global default.

    Returns:
        The batch ID string on success, or None on failure.
    """
    if not tasks:
        return None

    api_key = _get_api_key()
    if not api_key:
        print("batch: no API key found in ~/.claude/.credentials.json")
        return None

    resolved_model = _resolve_model(model)
    requests_payload = [_task_to_batch_request(t, resolved_model) for t in tasks]
    body = json.dumps({"requests": requests_payload}).encode()

    req = urllib.request.Request(
        _BATCH_BASE_URL,
        data=body,
        headers=_build_headers(api_key),
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data: dict = json.loads(resp.read())
        return data.get("id")
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read().decode()
        except Exception:
            err_body = str(exc)
        print(f"batch: HTTP {exc.code} when submitting batch: {err_body}")
        return None
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        print(f"batch: error submitting batch: {exc}")
        return None


def check_batch(batch_id: str) -> dict:
    """Fetch the current status of a batch.

    Args:
        batch_id: The batch ID returned by submit_batch.

    Returns:
        A dict with at minimum ``id``, ``processing_status``, and
        ``request_counts``. Returns an empty dict on error.
    """
    api_key = _get_api_key()
    if not api_key:
        print("batch: no API key found")
        return {}

    url = f"{_BATCH_BASE_URL}/{batch_id}"
    req = urllib.request.Request(url, headers=_build_headers(api_key), method="GET")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data: dict = json.loads(resp.read())
        return {
            "id": data.get("id", batch_id),
            "processing_status": data.get("processing_status", "unknown"),
            "request_counts": data.get("request_counts", {}),
        }
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read().decode()
        except Exception:
            err_body = str(exc)
        print(f"batch: HTTP {exc.code} checking batch {batch_id}: {err_body}")
        return {}
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        print(f"batch: error checking batch {batch_id}: {exc}")
        return {}


def collect_results(batch_id: str) -> list[dict]:
    """Retrieve results from a completed batch.

    Reads the JSONL streaming response and returns a list of result dicts.

    Args:
        batch_id: The batch ID to retrieve results for.

    Returns:
        A list of dicts, each with ``custom_id`` and ``result`` keys.
        ``result`` contains ``type`` (``"succeeded"`` or ``"errored"``) and,
        on success, a ``message`` dict.
    """
    api_key = _get_api_key()
    if not api_key:
        print("batch: no API key found")
        return []

    url = f"{_BATCH_BASE_URL}/{batch_id}/results"
    req = urllib.request.Request(url, headers=_build_headers(api_key), method="GET")

    results: list[dict] = []
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read().decode()
        except Exception:
            err_body = str(exc)
        print(f"batch: HTTP {exc.code} collecting results for {batch_id}: {err_body}")
        return []
    except (urllib.error.URLError, OSError) as exc:
        print(f"batch: error collecting results for {batch_id}: {exc}")
        return []

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            results.append(obj)
        except json.JSONDecodeError:
            print(f"batch: skipping unparseable result line: {line!r}")

    return results


def process_batch_results(results: list[dict]) -> None:
    """Update tasks in the DB based on batch results.

    For each result:
    - On success (``type == "succeeded"``): sets status to COMPLETED and
      stores the response text in ``result_summary``.
    - On failure (``type == "errored"``): sets status to FAILED and
      records the error in ``result_summary``.

    Args:
        results: List of result dicts as returned by collect_results.
    """
    for item in results:
        custom_id = item.get("custom_id")
        result = item.get("result", {})
        if custom_id is None:
            continue

        try:
            task_id = int(custom_id)
        except (ValueError, TypeError):
            print(f"batch: skipping result with non-integer custom_id {custom_id!r}")
            continue

        task = db.get_task(task_id)
        if task is None:
            print(f"batch: task {task_id} not found in DB, skipping")
            continue

        result_type = result.get("type", "errored")
        if result_type == "succeeded":
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            # Extract text content from the response message
            message = result.get("message", {})
            content_blocks = message.get("content", [])
            text_parts = [
                block.get("text", "")
                for block in content_blocks
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            task.result_summary = "\n".join(text_parts) if text_parts else json.dumps(message)
        else:
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now()
            error = result.get("error", {})
            task.result_summary = (
                f"Batch error: {error.get('type', 'unknown')} - {error.get('message', '')}"
            )

        db.update_task(task)


def run_batch_now(max_tasks: int = 50) -> tuple[int, str | None]:
    """Fetch pending tasks and submit them to the Batch API.

    Args:
        max_tasks: Maximum number of pending tasks to include in this batch.

    Returns:
        A tuple of (number of tasks submitted, batch_id or None on failure).
    """
    # Also check config for max_tasks override when called with default
    if max_tasks == 50:
        try:
            from wise_magpie import config
            cfg_max = config.get("batch", "max_tasks", None)
            if cfg_max is not None:
                max_tasks = int(cfg_max)
        except Exception:
            pass

    pending = db.get_tasks_by_status(TaskStatus.PENDING)
    tasks = pending[:max_tasks]

    if not tasks:
        return 0, None

    batch_id = submit_batch(tasks)
    return len(tasks), batch_id
