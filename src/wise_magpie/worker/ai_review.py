"""AI-powered code review for completed task branches."""

import json
import logging
import re

from wise_magpie.worker.executor import execute_task
from wise_magpie.worker.sandbox import get_branch_diff

logger = logging.getLogger(__name__)

_REVIEW_PROMPT_TEMPLATE = """\
You are a senior code reviewer. Review this code diff for the task "{task_title}".

Evaluate:
1. Correctness and logic errors
2. Security issues (injection, data exposure, etc.)
3. Test coverage adequacy
4. Code style and maintainability

Diff:
{diff}

Respond with a JSON object:
{{"verdict": "approved"|"needs_revision", "score": 0-10, "notes": "specific feedback"}}

Be concise. Focus on critical issues only.\
"""

_MAX_DIFF_CHARS = 8000
_MAX_COST_USD = 0.10


def review_branch(
    task_id: int | None,
    task_title: str,
    repo_path: str,
    branch_name: str,
    base_branch: str,
    model: str = "claude-sonnet-4-6",
) -> dict:
    """Review a completed task branch using Claude.

    Returns a dict with keys: verdict, score, notes.
    """
    diff = get_branch_diff(repo_path, branch_name, base_branch)

    if not diff or not diff.strip():
        return {"verdict": "skip", "score": None, "notes": "No changes detected"}

    if len(diff) > _MAX_DIFF_CHARS:
        diff = diff[:_MAX_DIFF_CHARS]

    prompt = _REVIEW_PROMPT_TEMPLATE.format(
        task_title=task_title,
        diff=diff,
    )

    result = execute_task(
        prompt=prompt,
        work_dir=repo_path,
        task_id=task_id,
        max_budget_usd=_MAX_COST_USD,
        model=model,
    )

    raw_output = result.output or ""

    # Try to extract JSON from the response.
    # Claude may wrap the JSON in markdown code fences.
    json_match = re.search(r"\{.*?\}", raw_output, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group())
            # Normalise expected keys.
            return {
                "verdict": parsed.get("verdict", "unknown"),
                "score": parsed.get("score"),
                "notes": parsed.get("notes", ""),
            }
        except json.JSONDecodeError:
            pass

    # Fallback: return raw output as notes.
    return {"verdict": "unknown", "score": None, "notes": raw_output}


def format_review_summary(review_result: dict) -> str:
    """Format a review result dict into a human-readable string."""
    verdict = review_result.get("verdict", "unknown")
    score = review_result.get("score")
    notes = review_result.get("notes", "")

    verdict_label = {
        "approved": "Approved",
        "needs_revision": "Needs Revision",
        "skip": "Skipped",
        "unknown": "Unknown",
    }.get(verdict, verdict.capitalize() if verdict else "Unknown")

    lines = [f"**Verdict:** {verdict_label}"]

    if score is not None:
        lines.append(f"**Score:** {score}/10")

    if notes:
        lines.append(f"**Notes:** {notes}")

    return "\n".join(lines)
