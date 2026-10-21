"""Codex CLI adapter: one-shot `codex exec --json` with Playwright MCP as the only tools.

Settings come from bench/codex/config.toml (model, reasoning effort, features off, Playwright
allow-list), written to an isolated CODEX_HOME (default ~/.codex-bench) so the user's own Codex
config, memories, skills and plugins stay out. Only auth.json is shared, as a symlink to
~/.codex/auth.json, so a token refresh by either copy keeps the other logged in.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path

from bench.adapters.hermes_playwright import DOWNLOADS
from bench.tasks import ROOT

TEMPLATE = ROOT / "bench" / "codex" / "config.toml"
HOME = Path(os.environ.get("CODEX_BENCH_HOME", Path.home() / ".codex-bench"))
CHROMIUM = os.environ.get("PLAYWRIGHT_CHROMIUM", str(Path.home() / ".hermes/tools/chromium-1208/chrome-linux64/chrome"))


def _codex() -> str:
    found = os.environ.get("CODEX_BIN") or shutil.which("codex")
    if found:
        return found
    # The VS Code extension ships its own binary.
    bundled = sorted(glob.glob(str(Path.home() / ".vscode/extensions/openai.chatgpt-*/bin/*/codex")))
    if not bundled:
        raise SystemExit("codex not found: install it or set CODEX_BIN")
    return bundled[-1]


def _setup_home() -> str:
    HOME.mkdir(parents=True, exist_ok=True)
    cfg = TEMPLATE.read_text().replace("{ROOT}", str(ROOT)).replace("{CHROMIUM}", CHROMIUM)
    (HOME / "config.toml").write_text(cfg)
    auth = HOME / "auth.json"
    if not auth.exists():
        auth.symlink_to(Path.home() / ".codex" / "auth.json")
    return re.search(r'^model = "([^"]+)"', cfg, re.M).group(1)


def version() -> str | None:
    try:
        return subprocess.run([_codex(), "--version"], capture_output=True, text=True, timeout=30).stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def run(prompt: str, workdir: Path, out_dir: Path, budget_s: int, model: str | None = None) -> dict:
    default_model = _setup_home()
    shutil.rmtree(DOWNLOADS, ignore_errors=True)
    DOWNLOADS.mkdir(parents=True)
    cmd = [_codex(), "exec", "--json", "--ephemeral", "--skip-git-repo-check", "--strict-config",
           "--ignore-rules", "-s", "read-only", "-C", str(workdir)]
    if model:
        cmd += ["-m", model]
    cmd.append(prompt)
    transcript = out_dir / "transcript.jsonl"
    t0 = time.monotonic()
    timed_out = False
    with transcript.open("w") as out, (out_dir / "stderr.log").open("w") as err:
        proc = subprocess.Popen(cmd, cwd=workdir, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                env={**os.environ, "CODEX_HOME": str(HOME)})
        try:
            proc.wait(timeout=budget_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            proc.wait()
    wall = time.monotonic() - t0
    return {"wall_s": round(wall, 1), "exit_code": proc.returncode, "timed_out": timed_out,
            **parse_transcript(transcript), "model": model or default_model}


def parse_transcript(path: Path) -> dict:
    tools: Counter[str] = Counter()
    tool_inputs: list[str] = []
    final_text = ""
    usage = Counter()
    for line in path.read_text(errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        item = ev.get("item") or {}
        if ev.get("type") == "item.completed":
            kind = item.get("type")
            if kind == "agent_message":
                final_text = item.get("text", "")
            elif kind == "mcp_tool_call":
                tools[f"mcp__{item.get('server')}__{item.get('tool')}"] += 1
                tool_inputs.append(json.dumps(item.get("arguments", "")))
            elif kind in ("command_execution", "file_change", "web_search"):  # should never happen
                tools[kind] += 1
                tool_inputs.append(json.dumps(item))
        elif ev.get("type") == "turn.completed":
            usage.update({k: v for k, v in (ev.get("usage") or {}).items() if isinstance(v, int)})
    # Codex counts cached tokens inside input_tokens; split them out like Hermes does.
    cached = usage.get("cached_input_tokens", 0)
    return {
        "final_text": final_text,
        "session_id": None,
        "tool_calls": sum(tools.values()),
        "tools": dict(tools),
        "tool_inputs": tool_inputs,
        "tokens_in": usage.get("input_tokens", 0) - cached if usage else None,
        "tokens_out": usage.get("output_tokens") if usage else None,
        "tokens_total": usage.get("input_tokens", 0) + usage.get("output_tokens", 0) if usage else None,
        "tokens_cache_read": cached if usage else None,
    }
