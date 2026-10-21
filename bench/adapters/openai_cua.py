"""OpenAI computer-use agent (the technology behind Operator / ChatGPT agent mode).

Runs bench/cua/agent.mjs: the Responses API `computer` tool with gpt-6-luna (medium effort, as the
other harnesses) driving a local headless Chromium through Playwright. Screenshots in, mouse and
keyboard actions out; no DOM, no JavaScript. Needs OPENAI_API_KEY (pay-per-token API billing, not
a ChatGPT plan) and `./setup.sh playwright`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from bench.adapters.hermes import parse_transcript
from bench.adapters.hermes_playwright import DOWNLOADS
from bench.tasks import ROOT

AGENT = ROOT / "bench" / "cua" / "agent.mjs"
MODEL = os.environ.get("OPENAI_CUA_MODEL", "gpt-6-luna")
EFFORT = os.environ.get("OPENAI_CUA_EFFORT", "medium")
CHROMIUM = os.environ.get("PLAYWRIGHT_CHROMIUM", str(Path.home() / ".hermes/tools/chromium-1208/chrome-linux64/chrome"))


def version() -> str:
    return f"bench/cua/agent.mjs (Responses API computer tool, {MODEL}, effort {EFFORT})"


def run(prompt: str, workdir: Path, out_dir: Path, budget_s: int, model: str | None = None) -> dict:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("openai_cua needs OPENAI_API_KEY")
    shutil.rmtree(DOWNLOADS, ignore_errors=True)
    DOWNLOADS.mkdir(parents=True)
    url = re.search(r"https?://[^\s]+?(?=[.,]?(\s|$))", prompt).group(0)
    task = {"prompt": prompt, "url": url, "out_dir": str(out_dir), "budget_s": budget_s,
            "model": model or MODEL, "effort": EFFORT, "downloads": str(DOWNLOADS), "chromium": CHROMIUM}
    (workdir / "task.json").write_text(json.dumps(task))
    t0 = time.monotonic()
    timed_out = False
    with (out_dir / "stderr.log").open("w") as err:
        proc = subprocess.Popen(["node", str(AGENT), str(workdir / "task.json")], cwd=workdir,
                                stdout=err, stderr=err, stdin=subprocess.DEVNULL)
        try:
            proc.wait(timeout=budget_s + 30)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            proc.wait()
    wall = time.monotonic() - t0
    res = parse_transcript(out_dir / "transcript.jsonl")
    return {"wall_s": round(wall, 1), "exit_code": proc.returncode,
            "timed_out": timed_out or wall >= budget_s, **res}
