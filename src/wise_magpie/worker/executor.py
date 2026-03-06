"""Claude CLI execution wrapper."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime

from wise_magpie import config, constants
from wise_magpie.quota.tracker import record_usage

# Patterns that indicate a rate limit (not a task failure).
_RATE_LIMIT_PATTERNS = [
    re.compile(r"hit your limit", re.IGNORECASE),
    re.compile(r"rate.?limit", re.IGNORECASE),
    re.compile(r"resets?\s+\d+[ap]m", re.IGNORECASE),
    re.compile(r"too many requests", re.IGNORECASE),
    re.compile(r"overloaded", re.IGNORECASE),
]


def _is_rate_limit_error(text: str) -> bool:
    """Return True if *text* looks like a rate-limit / quota-exhaustion error."""
    return any(p.search(text) for p in _RATE_LIMIT_PATTERNS)


@dataclass
class ExecutionResult:
    """Result from a Claude CLI execution."""
    success: bool
    output: str
    cost_usd: float
    input_tokens: int
    output_tokens: int
    duration_seconds: float
    error: str = ""
    is_rate_limited: bool = False


def build_claude_command(
    prompt: str,
    work_dir: str,
    max_budget_usd: float | None = None,
    model: str | None = None,
    extra_flags: list[str] | None = None,
) -> list[str]:
    """Build the claude CLI command."""
    cfg = config.load_config()
    claude_cfg = cfg.get("claude", {})
    model = model or claude_cfg.get("model", constants.DEFAULT_MODEL)
    max_budget = max_budget_usd or cfg.get("budget", {}).get("max_task_usd", constants.MAX_TASK_BUDGET_USD)
    flags = extra_flags or claude_cfg.get("extra_flags", [])

    cmd = [
        "claude",
        "-p", prompt,
        "--output-format", "json",
        "--max-turns", "50",
        f"--max-budget-usd={max_budget}",
        "--dangerously-skip-permissions",
    ]

    # Add fallback model if configured (claude uses it when primary is rate-limited).
    fallback = claude_cfg.get("fallback_model", "sonnet")
    if fallback:
        # Resolve alias → full model ID
        resolved = constants.MODEL_ALIASES.get(fallback, fallback)
        if resolved != model:  # no point falling back to the same model
            cmd.extend(["--fallback-model", resolved])

    for flag in flags:
        cmd.append(flag)
    return cmd


def execute_task(
    prompt: str,
    work_dir: str,
    task_id: int | None = None,
    max_budget_usd: float | None = None,
    model: str | None = None,
    timeout_seconds: int = 600,
) -> ExecutionResult:
    """Execute a task using the Claude CLI.

    Runs `claude -p <prompt> --output-format json` in the given working directory.
    Records usage in the database.
    """
    cmd = build_claude_command(prompt, work_dir, max_budget_usd, model=model)
    start_time = datetime.now()

    # Remove CLAUDECODE env var to allow launching claude from within a session
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    try:
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
    except subprocess.TimeoutExpired:
        duration = (datetime.now() - start_time).total_seconds()
        return ExecutionResult(
            success=False,
            output="",
            cost_usd=0.0,
            input_tokens=0,
            output_tokens=0,
            duration_seconds=duration,
            error="Task timed out",
        )
    except FileNotFoundError:
        return ExecutionResult(
            success=False,
            output="",
            cost_usd=0.0,
            input_tokens=0,
            output_tokens=0,
            duration_seconds=0.0,
            error="claude CLI not found. Is Claude Code installed?",
        )

    duration = (datetime.now() - start_time).total_seconds()

    # Parse JSON output
    input_tokens = 0
    output_tokens = 0
    cost_usd = 0.0
    output_text = result.stdout

    try:
        data = json.loads(result.stdout)
        output_text = data.get("result", result.stdout)
        input_tokens = data.get("input_tokens", 0)
        output_tokens = data.get("output_tokens", 0)
        cost_usd = data.get("cost_usd", 0.0)

        # Try to extract from usage stats if available
        if "usage" in data:
            usage = data["usage"]
            input_tokens = usage.get("input_tokens", input_tokens)
            output_tokens = usage.get("output_tokens", output_tokens)
    except (json.JSONDecodeError, TypeError):
        pass

    # Record usage (use the model actually passed, not just config default)
    if model is None:
        cfg = config.load_config()
        model = cfg.get("claude", {}).get("model", constants.DEFAULT_MODEL)
    record_usage(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        task_id=task_id,
        autonomous=True,
    )

    success = result.returncode == 0
    error = result.stderr if not success else ""

    # Detect rate-limit errors from either stderr or stdout.
    rate_limited = _is_rate_limit_error(error) or _is_rate_limit_error(output_text)

    return ExecutionResult(
        success=success,
        output=output_text,
        cost_usd=cost_usd,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_seconds=duration,
        error=error,
        is_rate_limited=rate_limited,
    )
