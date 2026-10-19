"""Hermes Agent adapter: one-shot `hermes chat` with the stream-json event log."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections import Counter
from pathlib import Path

HERMES = os.environ.get("HERMES_BIN", str(Path.home() / ".local/bin/hermes"))

# browser = vault tool, browser-use = browser_exec (default Browser Use driver on Hermes's
# own headless Chromium). No terminal/file/code tools, so the agent can only act through
# the browser and nothing needs an approval prompt.
DEFAULT_TOOLSETS = "browser,browser-use"


def run(prompt: str, workdir: Path, out_dir: Path, budget_s: int, model: str | None = None,
        toolsets: str = DEFAULT_TOOLSETS) -> dict:
    cmd = [HERMES, "chat", "-q", prompt, "--format", "stream-json", "-t", toolsets,
           "--ignore-rules", "--source", "tool", "--run-budget", str(budget_s)]
    if model:
        cmd += ["-m", model]
    transcript = out_dir / "transcript.jsonl"
    t0 = time.monotonic()
    timed_out = False
    with transcript.open("w") as out, (out_dir / "stderr.log").open("w") as err:
        proc = subprocess.Popen(cmd, cwd=workdir, stdout=out, stderr=err, stdin=subprocess.DEVNULL)
        try:
            proc.wait(timeout=budget_s + 60)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            proc.wait()
    wall = time.monotonic() - t0
    return {"wall_s": round(wall, 1), "exit_code": proc.returncode, "timed_out": timed_out,
            **parse_transcript(transcript)}


def parse_transcript(path: Path) -> dict:
    tools: Counter[str] = Counter()
    tool_inputs: list[str] = []
    result: dict = {}
    text_chunks: list[str] = []
    for line in path.read_text(errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        kind = ev.get("type")
        if kind == "tool_use":
            tools[ev.get("name", "?")] += 1
            tool_inputs.append(json.dumps(ev.get("input", "")))
        elif kind == "text":
            text_chunks.append(ev.get("text", ""))
        elif kind == "result":
            result = ev
    tokens = result.get("tokens") or {}
    return {
        "final_text": result.get("text", "".join(text_chunks)),
        "session_id": result.get("session_id"),
        "tool_calls": sum(tools.values()),
        "tools": dict(tools),
        "tool_inputs": tool_inputs,
        "tokens_in": tokens.get("input"),
        "tokens_out": tokens.get("output"),
        "tokens_total": tokens.get("total"),
        "tokens_cache_read": tokens.get("cache_read"),
    }
