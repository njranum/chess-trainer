"""
LLM transport (Design.md §2, §7): Claude Code headless (`claude -p`),
authenticated by the local CLI session or a CLAUDE_CODE_OAUTH_TOKEN env var.
Never in the request path — only the `tag` management command calls this.

The transport is a plain callable (prompt → text) so the tagging logic is
testable with a stub and the backend is swappable (API later, if ever).
"""

import subprocess
import tempfile

TIMEOUT_S = 300


def claude_headless(prompt: str) -> str:
    """One batched tagging call. Raises on non-zero exit or timeout —
    callers treat any failure as a failed batch (self-requeues).

    Runs from a neutral cwd with --max-turns 1: this is a pure text
    completion; without these, headless Claude may load project context and
    wander the repo with tools instead of answering."""
    result = subprocess.run(
        ["claude", "-p", "--model", "claude-sonnet-5", "--max-turns", "1"],
        input=prompt, capture_output=True, text=True, timeout=TIMEOUT_S,
        cwd=tempfile.gettempdir(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude -p failed ({result.returncode}): "
                           f"{result.stderr[:500]}")
    return result.stdout
