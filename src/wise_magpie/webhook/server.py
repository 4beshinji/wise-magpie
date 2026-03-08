"""Lightweight GitHub Webhook HTTP server using stdlib http.server."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from wise_magpie import db
from wise_magpie.models import Task, TaskSource
from wise_magpie.tasks.prioritizer import calculate_priority

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Priority constants
# ---------------------------------------------------------------------------

PRIORITY_CI_FAILURE = 75.0
PRIORITY_ISSUE = 60.0
PRIORITY_PR = 40.0
PRIORITY_PUSH = 30.0


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def _verify_signature(body: bytes, secret: str, signature_header: str) -> bool:
    """Return True if the HMAC-SHA256 signature matches.

    Rejects all requests when no secret is configured — callers should
    not start the server without a secret in the first place.
    """
    if not secret:
        logger.warning("Webhook request rejected: no secret configured")
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


# ---------------------------------------------------------------------------
# Task creation helpers
# ---------------------------------------------------------------------------

def _insert_task(title: str, description: str, priority: float) -> Task:
    """Insert a new task into the database and return it."""
    db.init_db()
    task = Task(
        title=title,
        description=description,
        source=TaskSource.ISSUE,
        priority=priority,
        created_at=datetime.now(),
    )
    if priority == 0.0:
        task.priority = calculate_priority(task)
    task.id = db.insert_task(task)
    return task


def _handle_issues(payload: dict[str, Any]) -> tuple[int, str]:
    action = payload.get("action", "")
    if action not in ("opened", "labeled"):
        return 200, f"Ignored issues action: {action}"

    issue = payload.get("issue", {})
    title = f"Fix GitHub issue: {issue.get('title', '(no title)')}"
    body_text = (issue.get("body") or "")[:1000]
    description = f"Fix GitHub issue: {issue.get('title', '')}\n\n{body_text}"

    task = _insert_task(title, description, PRIORITY_ISSUE)
    msg = f"Task #{task.id} created for issue action={action}"
    logger.info(msg)
    return 201, msg


def _handle_pull_request(payload: dict[str, Any]) -> tuple[int, str]:
    action = payload.get("action", "")
    if action != "opened":
        return 200, f"Ignored pull_request action: {action}"

    pr = payload.get("pull_request", {})
    title = f"Review PR: {pr.get('title', '(no title)')}"
    body_text = (pr.get("body") or "")[:500]
    description = f"Review PR: {pr.get('title', '')}\n{body_text}"

    task = _insert_task(title, description, PRIORITY_PR)
    msg = f"Task #{task.id} created for PR action={action}"
    logger.info(msg)
    return 201, msg


def _handle_workflow_run(payload: dict[str, Any]) -> tuple[int, str]:
    action = payload.get("action", "")
    if action != "completed":
        return 200, f"Ignored workflow_run action: {action}"

    workflow_run = payload.get("workflow_run", {})
    conclusion = workflow_run.get("conclusion", "")
    if conclusion != "failure":
        return 200, f"Ignored workflow_run conclusion: {conclusion}"

    repo = payload.get("repository", {})
    title = f"Fix CI failure: {workflow_run.get('name', '(unnamed)')}"
    description = (
        f"Fix CI failure: {workflow_run.get('name', '')}\n"
        f"Repo: {repo.get('full_name', '')}"
    )

    task = _insert_task(title, description, PRIORITY_CI_FAILURE)
    msg = f"Task #{task.id} created for CI failure"
    logger.info(msg)
    return 201, msg


def _handle_push(payload: dict[str, Any]) -> tuple[int, str]:
    repo = payload.get("repository", {})
    ref = payload.get("ref", "")
    title = f"Run lint/test after push to {ref} in {repo.get('full_name', '')}"
    description = title

    task = _insert_task(title, description, PRIORITY_PUSH)
    msg = f"Task #{task.id} created for push event"
    logger.info(msg)
    return 201, msg


# ---------------------------------------------------------------------------
# Handler dispatch table
# ---------------------------------------------------------------------------

_EVENT_HANDLERS = {
    "issues": _handle_issues,
    "pull_request": _handle_pull_request,
    "workflow_run": _handle_workflow_run,
    "push": _handle_push,
}


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class _WebhookHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the GitHub webhook server."""

    # Injected by start_server
    webhook_secret: str = ""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        logger.debug(format, *args)

    # ------------------------------------------------------------------
    # GET /health
    # ------------------------------------------------------------------

    def _handle_health(self) -> None:
        body = b'{"status": "ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------
    # POST /webhook/github
    # ------------------------------------------------------------------

    # Maximum request body size (1 MB) to prevent memory exhaustion.
    _MAX_BODY_SIZE = 1_048_576

    def _handle_github_webhook(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        if length > self._MAX_BODY_SIZE:
            self._respond(413, "Request body too large")
            return
        raw_body = self.rfile.read(length)

        # Signature verification
        sig_header = self.headers.get("X-Hub-Signature-256", "")
        if not _verify_signature(raw_body, self.__class__.webhook_secret, sig_header):
            self._respond(403, "Invalid signature")
            return

        # Parse JSON
        try:
            payload: dict[str, Any] = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            self._respond(400, f"Invalid JSON: {exc}")
            return

        event = self.headers.get("X-GitHub-Event", "")
        handler = _EVENT_HANDLERS.get(event)
        if handler is None:
            self._respond(200, f"Ignored unknown event: {event}")
            return

        try:
            status_code, message = handler(payload)
        except Exception:  # noqa: BLE001
            logger.exception("Error handling event %s", event)
            self._respond(500, "Internal server error")
            return

        self._respond(status_code, message)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._handle_health()
        else:
            self._respond(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/webhook/github":
            self._handle_github_webhook()
        else:
            self._respond(404, "Not found")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _respond(self, status: int, message: str) -> None:
        body = json.dumps({"message": message}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def start_server(host: str = "127.0.0.1", port: int = 8765, secret: str = "") -> None:
    """Start the webhook HTTP server (blocking)."""
    if not secret:
        logger.error(
            "Webhook secret is not configured. Set webhook.secret in config "
            "or WISE_MAGPIE_WEBHOOK_SECRET env var. Refusing to start without "
            "authentication."
        )
        raise SystemExit(1)

    # Inject secret into handler class
    _WebhookHandler.webhook_secret = secret

    server = HTTPServer((host, port), _WebhookHandler)
    logger.info("Webhook server listening on %s:%d", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Webhook server stopped")
    finally:
        server.server_close()
