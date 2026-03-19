"""Tests for webhook/server.py — security headers and request handling."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch

import pytest

from wise_magpie.webhook.server import _WebhookHandler


class _FakeRequest(BytesIO):
    """Mimic a socket makefile() result for BaseHTTPRequestHandler."""

    def makefile(self, *args, **kwargs):
        return self


def _make_handler(method: str, path: str, body: bytes = b"", headers: dict | None = None) -> _WebhookHandler:
    """Construct a handler with a fake request and capture the response."""
    headers = headers or {}
    # Build raw HTTP request
    header_lines = f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n"
    if body:
        header_lines += f"Content-Length: {len(body)}\r\n"
    for k, v in headers.items():
        header_lines += f"{k}: {v}\r\n"
    header_lines += "\r\n"

    raw = header_lines.encode() + body
    request = _FakeRequest(raw)
    response = BytesIO()

    handler = _WebhookHandler(request, ("127.0.0.1", 9999), None)
    return handler


def _get_response_bytes(method: str, path: str, body: bytes = b"", headers: dict | None = None) -> bytes:
    """Send a fake HTTP request and return the raw response bytes."""
    headers = headers or {}
    header_lines = f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n"
    if body:
        header_lines += f"Content-Length: {len(body)}\r\n"
    for k, v in headers.items():
        header_lines += f"{k}: {v}\r\n"
    header_lines += "\r\n"

    raw = header_lines.encode() + body
    rfile = BytesIO(raw)
    wfile = BytesIO()

    # BaseHTTPRequestHandler reads from rfile and writes to wfile
    # We need to patch the handler to capture output
    with patch.object(_WebhookHandler, "__init__", lambda self, *a, **kw: None):
        handler = _WebhookHandler.__new__(_WebhookHandler)
        handler.rfile = BytesIO(body)
        handler.wfile = wfile
        handler.requestline = f"{method} {path} HTTP/1.1"
        handler.request_version = "HTTP/1.1"
        handler.command = method
        handler.path = path
        handler.headers = {}
        handler.webhook_secret = ""

        # Use email.message for headers
        from http.client import HTTPResponse
        from email.message import Message

        msg = Message()
        for k, v in headers.items():
            msg[k] = v
        if body:
            msg["Content-Length"] = str(len(body))
        handler.headers = msg
        handler.close_connection = True

        if method == "GET":
            handler.do_GET()
        elif method == "POST":
            handler.do_POST()

        return wfile.getvalue()


class TestSecurityHeaders:
    """Verify CSP and other security headers are present on all responses."""

    def _assert_security_headers(self, raw_response: bytes) -> None:
        response_str = raw_response.decode("utf-8", errors="replace")
        assert "Content-Security-Policy:" in response_str
        assert "default-src 'none'" in response_str
        assert "frame-ancestors 'none'" in response_str
        assert "X-Content-Type-Options: nosniff" in response_str
        assert "X-Frame-Options: DENY" in response_str

    def test_health_endpoint_has_security_headers(self):
        raw = _get_response_bytes("GET", "/health")
        self._assert_security_headers(raw)

    def test_404_has_security_headers(self):
        raw = _get_response_bytes("GET", "/nonexistent")
        self._assert_security_headers(raw)

    def test_webhook_invalid_json_has_security_headers(self):
        raw = _get_response_bytes(
            "POST",
            "/webhook/github",
            body=b"not json",
            headers={"X-GitHub-Event": "push"},
        )
        self._assert_security_headers(raw)

    @patch("wise_magpie.webhook.server.db")
    def test_webhook_ignored_event_has_security_headers(self, mock_db):
        raw = _get_response_bytes(
            "POST",
            "/webhook/github",
            body=json.dumps({"action": "opened"}).encode(),
            headers={"X-GitHub-Event": "unknown_event"},
        )
        self._assert_security_headers(raw)
