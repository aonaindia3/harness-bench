"""Usage-limit detection: tell "the provider stopped us" apart from "the agent failed".

A harness that runs into its plan's usage limit (ChatGPT Plus) or the API's quota exits with an
error part-way through a task. Scored, that attempt would quietly lower the harness's number, so a
runner leaves it unscored and stops with EXIT_LIMITED; re-running with the same --out resumes it.

Matching is deliberately broad: a false positive only means the task is retried later, while a
miss scores a provider error as an agent failure. Extend PATTERN when a new limit message shows up.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

EXIT_LIMITED = 75  # EX_TEMPFAIL: try again later

PATTERN = re.compile(r"usage.?limit|rate.?limit|too many requests|insufficient_quota|\bquota\b", re.I)

# Transcript events that carry the agent's own errors (Hermes and bench/cua "result"; the cua
# agent's error report; Codex exec's "error" and "turn.failed"). Tool results are never read:
# they hold page and file contents, which can say "429" or "rate limit" on their own.
ERROR_EVENTS = {"result", "error", "turn.failed"}


def _error_texts(attempt: Path):
    stderr = attempt / "stderr.log"
    if stderr.exists():
        yield from stderr.read_text(errors="replace").splitlines()
    transcript = attempt / "transcript.jsonl"
    if not transcript.exists():
        return
    for line in transcript.read_text(errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") in ERROR_EVENTS or (ev.get("name") == "agent" and ev.get("is_error")):
            yield json.dumps(ev, ensure_ascii=False)


def limited(attempt: Path, exit_code: int | None) -> str | None:
    """The offending line if this attempt ended on a usage limit, else None. A clean exit never
    counts, whatever the agent said."""
    if not exit_code:
        return None
    for text in _error_texts(attempt):
        if PATTERN.search(text):
            return text.strip()[:500]
    return None
