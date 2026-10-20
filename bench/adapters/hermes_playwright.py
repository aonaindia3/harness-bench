"""Hermes with Playwright MCP as its browser instead of the built-in agent-browser tools.

Same Hermes, model and prompts as the `hermes` adapter; only the browser tools differ. Uses the
`bench-playwright` profile (see README "Hermes setup"): built-in browser toolset disabled, and a
`playwright` MCP server limited to page-level tools (no browser_run_code_unsafe, network bodies or
file upload), running the same Chromium build Hermes uses.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from bench.adapters import hermes

PROFILE = os.environ.get("HERMES_PLAYWRIGHT_PROFILE", "bench-playwright")
# The profile's --output-dir: where the browser saves downloads. Emptied before every attempt so
# one task never sees another task's files (bench.run only lets the agent open files from here).
DOWNLOADS = Path(os.environ.get("HERMES_PLAYWRIGHT_DOWNLOADS", "/tmp/hb-playwright-out"))
version = hermes.version


def run(prompt: str, workdir: Path, out_dir: Path, budget_s: int, model: str | None = None) -> dict:
    shutil.rmtree(DOWNLOADS, ignore_errors=True)
    DOWNLOADS.mkdir(parents=True)
    return hermes.run(prompt, workdir, out_dir, budget_s, model, profile=PROFILE, toolsets="playwright")
