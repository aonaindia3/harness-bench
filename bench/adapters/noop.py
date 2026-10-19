"""Does nothing. Used by `run.py --harness noop` to check servers, prompts and grading
without launching an agent (every task should score 0)."""

from __future__ import annotations

from pathlib import Path


def run(prompt: str, workdir: Path, out_dir: Path, budget_s: int, model: str | None = None) -> dict:
    (out_dir / "prompt.txt").write_text(prompt)
    return {"wall_s": 0.0, "exit_code": 0, "timed_out": False, "final_text": "", "tool_calls": 0,
            "tools": {}, "tool_inputs": [], "tokens_in": None, "tokens_out": None,
            "tokens_total": None, "tokens_cache_read": None}
