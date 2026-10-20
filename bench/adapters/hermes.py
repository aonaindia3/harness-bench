"""Hermes Agent adapter: one-shot `hermes chat` with the stream-json event log."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections import Counter
from pathlib import Path

HERMES = os.environ.get("HERMES_BIN", str(Path.home() / ".local/bin/hermes"))

# A dedicated profile (see README "Hermes setup") with browser.backend: off, i.e. Hermes's
# built-in agent-browser tools (navigate/snapshot/click/type/scroll/press/vision/console...).
# The default Browser Use driver (browser_exec) is only offered to sessions that also have the
# terminal toolset, which would let the agent read the benchmark files or curl the server.
PROFILE = os.environ.get("HERMES_BENCH_PROFILE", "bench")
TOOLSETS = os.environ.get("HERMES_BENCH_TOOLSETS", "browser")


def version() -> str | None:
    try:
        out = subprocess.run([HERMES, "--version"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.splitlines()[0].strip() if out else None


def run(prompt: str, workdir: Path, out_dir: Path, budget_s: int, model: str | None = None,
        profile: str = PROFILE, toolsets: str = TOOLSETS) -> dict:
    cmd = [HERMES, "-p", profile, "chat", "-q", prompt, "--format", "stream-json", "-t", toolsets,
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
    model = None
    text_chunks: list[str] = []
    for line in path.read_text(errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        kind = ev.get("type")
        if kind == "system" and ev.get("subtype") == "init":
            model = ev.get("model")
        elif kind == "tool_use":
            tools[ev.get("name", "?")] += 1
            tool_inputs.append(json.dumps(ev.get("input", "")))
        elif kind == "text":
            text_chunks.append(ev.get("text", ""))
        elif kind == "result":
            result = ev
    tokens = result.get("tokens") or {}
    return {
        "model": model,
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
