# Penetration Test Report

**Application:** wise-magpie
**Date:** 2026-03-08
**Scope:** Full application source code review, automated scanning (bandit), manual analysis
**Tester:** Automated security audit (wise-magpie autonomous task)

---

## Executive Summary

wise-magpie is a local daemon that autonomously executes Claude CLI tasks during
idle time. It includes a GitHub webhook server, MCP server, BLE GATT service,
swarm peer discovery, and Anthropic API integrations. The application runs
locally with user-level privileges and manages credentials from
`~/.claude/.credentials.json`.

**Total findings: 12**

| Severity | Count |
|----------|-------|
| Critical | 1     |
| High     | 3     |
| Medium   | 4     |
| Low      | 4     |

---

## Findings

### FINDING-01: Webhook Signature Verification Bypass When Secret Is Empty (Critical)

**File:** `src/wise_magpie/webhook/server.py:33-36`
**CWE:** CWE-306 (Missing Authentication for Critical Function)

**Description:**
The `_verify_signature()` function returns `True` when `secret` is empty.
The default configuration ships with `webhook.secret = ""`. This means the
webhook server accepts **any** unauthenticated POST request by default, allowing
an attacker on the network to inject arbitrary tasks into the queue (issues, PRs,
CI failures, pushes) without HMAC verification.

Since injected tasks are executed autonomously by the daemon with
`--dangerously-skip-permissions`, an attacker could craft a payload that causes
arbitrary code execution on the host.

**Evidence:**
```python
def _verify_signature(body: bytes, secret: str, signature_header: str) -> bool:
    if not secret:
        return True  # <-- bypasses all verification
```

**Remediation:**
- Refuse to start the webhook server if no secret is configured.
- Log a warning at startup if the secret is empty.
- Add documentation requiring a webhook secret for production use.

---

### FINDING-02: Command Execution with `--dangerously-skip-permissions` (High)

**File:** `src/wise_magpie/worker/executor.py:63`
**CWE:** CWE-78 (OS Command Injection)

**Description:**
Every autonomous task is executed with `--dangerously-skip-permissions`, which
disables Claude Code's permission checks. Combined with FINDING-01 (webhook task
injection) or any other task injection vector, this allows full arbitrary code
execution on the host system. The task prompt is constructed from user-controlled
data (GitHub issue titles, PR bodies, TODO comments) without sanitization.

**Evidence:**
```python
cmd = [
    "claude",
    "-p", prompt,
    "--output-format", "json",
    "--max-turns", "50",
    f"--max-budget-usd={max_budget}",
    "--dangerously-skip-permissions",
]
```

**Remediation:**
- This flag is architecturally required for autonomous operation. Document the
  risk prominently.
- Implement input sanitization on task prompts from external sources (webhooks).
- Consider adding an allowlist of permitted task patterns for webhook-sourced
  tasks.

---

### FINDING-03: No Content-Length Limit on Webhook Requests (High)

**File:** `src/wise_magpie/webhook/server.py:174-175`
**CWE:** CWE-400 (Uncontrolled Resource Consumption)

**Description:**
The webhook handler reads `Content-Length` bytes from the request body without
any upper bound. An attacker can send a multi-gigabyte `Content-Length` header to
cause memory exhaustion (denial of service).

**Evidence:**
```python
length = int(self.headers.get("Content-Length", 0))
raw_body = self.rfile.read(length)
```

**Remediation:**
- Add a maximum body size limit (e.g., 1 MB) and reject requests exceeding it.

---

### FINDING-04: Internal Error Messages Leak Stack Traces (High)

**File:** `src/wise_magpie/webhook/server.py:200`
**CWE:** CWE-209 (Information Exposure Through Error Message)

**Description:**
When an exception occurs in webhook event handling, the full exception string is
returned to the client in the HTTP response. This can leak internal paths, module
names, and other implementation details.

**Evidence:**
```python
except Exception as exc:
    logger.exception("Error handling event %s", event)
    self._respond(500, f"Internal error: {exc}")
```

**Remediation:**
- Return a generic error message to clients. Log the full exception server-side
  only.

---

### FINDING-05: SQL Injection via Dynamic Query Construction (Medium)

**File:** `src/wise_magpie/db.py:298-303`
**CWE:** CWE-89 (SQL Injection)

**Description:**
The `get_tasks_by_status()` function constructs SQL with f-string interpolation
for placeholders. While the current code only interpolates `?` placeholders
(generated from a count, not user data) and passes actual values via
parameterized queries, the pattern is fragile. Bandit flagged this as B608.

**Evidence:**
```python
placeholders = ",".join("?" for _ in statuses)
values = [s.value for s in statuses]
rows = conn.execute(
    f"SELECT * FROM tasks WHERE status IN ({placeholders}) ORDER BY ...",
    values,
)
```

**Actual Risk:** Low — the placeholders are always `?` characters derived from
enum values, not user input. The parameterized values prevent injection. However,
the pattern could be dangerous if refactored carelessly.

**Remediation:**
- No immediate action required, but consider adding a comment explaining why this
  pattern is safe.

---

### FINDING-06: URL Scheme Not Validated in urllib Calls (Medium)

**Files:**
- `src/wise_magpie/quota/claude_api.py:77`
- `src/wise_magpie/quota/batch.py:119,153,195`

**CWE:** CWE-918 (Server-Side Request Forgery)

**Description:**
Bandit B310 flagged `urllib.request.urlopen()` calls. If the URL constants were
ever configurable or influenced by user input, the `file://` scheme could be used
to read local files. Currently the URLs are hardcoded constants, but the batch
API constructs URLs by concatenating a base URL with a user-returned `batch_id`.

**Evidence:**
```python
url = f"{_BATCH_BASE_URL}/{batch_id}"
req = urllib.request.Request(url, headers=_build_headers(api_key), method="GET")
```

If `batch_id` contained `../../` or other path traversal, the URL would be
malformed but urllib would still attempt the request.

**Remediation:**
- Validate that `batch_id` matches an expected pattern (e.g., alphanumeric with
  hyphens only) before constructing URLs.

---

### FINDING-07: BLE GATT Service Has No Authentication (Medium)

**File:** `src/wise_magpie/ble/service.py`, `src/wise_magpie/ble/handler.py`
**CWE:** CWE-306 (Missing Authentication for Critical Function)

**Description:**
The BLE GATT service exposes commands (status, task listing, task creation, quota
query) without any authentication or pairing requirement. Any BLE device within
range can connect and inject tasks or read daemon status.

**Evidence:**
The `CommandCharacteristic` accepts writes from any connected device and
dispatches to `handler.dispatch()` which executes task creation directly.

**Remediation:**
- Require BLE pairing/bonding before accepting command writes.
- Add a shared secret or challenge-response mechanism.
- Document that BLE mode should only be used in trusted environments.

---

### FINDING-08: PID File Race Condition (Medium)

**File:** `src/wise_magpie/daemon/runner.py:51-62`
**CWE:** CWE-367 (TOCTOU Race Condition)

**Description:**
The `_is_running()` check and `_write_pid()` call are not atomic. Two daemon
instances started simultaneously could both pass the `_is_running()` check and
write their PID, leading to multiple daemons running concurrently.

**Remediation:**
- Use file locking (`fcntl.flock`) on the PID file to ensure mutual exclusion.

---

### FINDING-09: Database File Has No Access Control (Low)

**File:** `src/wise_magpie/db.py:116`
**CWE:** CWE-732 (Incorrect Permission Assignment)

**Description:**
The SQLite database at `~/.config/wise-magpie/wise-magpie.db` is created with
default permissions (typically 0644). Other users on a shared system could read
task data, usage logs, and activity patterns.

**Remediation:**
- Set file permissions to 0600 on the database file after creation.

---

### FINDING-10: Credentials File Read Without Permission Check (Low)

**Files:**
- `src/wise_magpie/quota/claude_api.py:40-43`
- `src/wise_magpie/quota/batch.py:33-43`

**CWE:** CWE-522 (Insufficiently Protected Credentials)

**Description:**
The application reads credentials from `~/.claude/.credentials.json` without
verifying that the file has restrictive permissions. If the credentials file is
world-readable, the OAuth token and API key could be exposed.

**Remediation:**
- Log a warning if the credentials file permissions are too open (not 0600).

---

### FINDING-11: MCP Server Has No Input Validation on task_id (Low)

**File:** `src/wise_magpie/mcp_server.py:216`
**CWE:** CWE-20 (Improper Input Validation)

**Description:**
The `_tool_get_task_status` function converts `args["task_id"]` with `int()` but
does not validate range. A very large integer or negative value is passed
directly to the database query. While SQLite handles this gracefully (returns no
rows), it could be unexpected.

**Remediation:**
- Validate that `task_id` is a positive integer.

---

### FINDING-12: Swarm Socket Path Predictable and World-Accessible (Low)

**File:** `src/wise_magpie/swarm/advertiser.py:261-272`
**CWE:** CWE-732 (Incorrect Permission Assignment)

**Description:**
The Unix datagram socket is created in the config directory with default
permissions. On shared systems, another user could create a peer socket and
inject false heartbeat frames, potentially influencing task scheduling decisions.

**Remediation:**
- Set restrictive permissions on the socket file.
- Validate the sender's UID on received frames.

---

## Automated Scanner Results

### Bandit (v1.9.4)

| Category | Count |
|----------|-------|
| SEVERITY.MEDIUM | 5 |
| SEVERITY.LOW | 36 |
| SEVERITY.HIGH | 0 |

Key findings:
- **B608** (SQL injection pattern): 1 instance in `db.py` — see FINDING-05
- **B310** (urllib urlopen): 4 instances — see FINDING-06
- **B110** (try/except/pass): 14 instances — mostly benign best-effort patterns
- **B603/B607** (subprocess calls): 18 instances — all use list-form arguments
  (no shell injection), but some use partial paths
- **B404** (subprocess import): 4 instances — informational only

### Manual Review Areas

| Area | Result |
|------|--------|
| Authentication bypass | FINDING-01 (webhook), FINDING-07 (BLE) |
| Session management | N/A (no web sessions; daemon uses PID file) |
| Brute-force protection | N/A (no login; rate limiting via circuit breaker) |
| IDOR | Not applicable (single-user local application) |
| Privilege escalation | FINDING-02 (dangerously-skip-permissions) |
| API fuzzing | FINDING-03 (unbounded Content-Length), FINDING-04 (error leak) |
| Access controls | FINDING-09 (DB perms), FINDING-12 (socket perms) |
| Least-privilege | FINDING-02 (all tasks run with full permissions) |

---

## Recommendations Summary

| Priority | Action |
|----------|--------|
| **Immediate** | Require webhook secret; refuse to start without one |
| **Immediate** | Add Content-Length limit to webhook server |
| **Immediate** | Sanitize error responses (don't leak exceptions to clients) |
| **Short-term** | Validate batch_id format before URL construction |
| **Short-term** | Add BLE authentication/pairing requirement |
| **Short-term** | Use file locking for PID file |
| **Short-term** | Set restrictive permissions on DB and socket files |
| **Long-term** | Consider task prompt sanitization for external sources |
| **Long-term** | Add per-source task allowlists for webhook-created tasks |
