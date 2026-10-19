"""MCP (stdio) server that exposes the current OSWorld VM to a harness.

Run with vendor/OSWorld/.venv/bin/python. bench/osworld_run.py writes the VM address of the
task in progress to runs/.osworld_current.json; every tool call reads it, so one static MCP
config serves all tasks.

Tools: screenshot, accessibility_tree, execute (pyautogui code), done (DONE/FAIL).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests
from mcp.server.fastmcp import FastMCP, Image

ROOT = Path(__file__).resolve().parent.parent
STATE = Path(os.environ.get("OSWORLD_BENCH_STATE", ROOT / "runs" / ".osworld_current.json"))
sys.path.insert(0, str(ROOT / "vendor" / "OSWorld"))

from desktop_env.controllers.python import PYAUTOGUI_PKGS_PREFIX, PythonController  # noqa: E402

mcp = FastMCP("osworld")


def _state() -> dict:
    return json.loads(STATE.read_text())


def _controller() -> PythonController:
    s = _state()
    return PythonController(vm_ip=s["vm_ip"], server_port=s["server_port"])


def _log(entry: dict) -> None:
    s = _state()
    with open(s["action_log"], "a") as f:
        f.write(json.dumps({"t": time.time(), **entry}) + "\n")


@mcp.tool()
def screenshot() -> Image:
    """Screenshot of the Ubuntu desktop (PNG, 1920x1080; coordinates are screen pixels)."""
    png = _controller().get_screenshot()
    if not png:
        raise RuntimeError("screenshot failed")
    attempt_dir = Path(_state()["action_log"]).parent
    shot = attempt_dir / f"shot_{len(list(attempt_dir.glob('shot_*.png'))):03d}.png"
    shot.write_bytes(png)
    _log({"tool": "screenshot", "file": shot.name})
    return Image(data=png, format="png")


@mcp.tool()
def accessibility_tree(max_chars: int = 30000) -> str:
    """The desktop's accessibility tree (XML), truncated to max_chars."""
    tree = _controller().get_accessibility_tree() or ""
    _log({"tool": "accessibility_tree", "chars": len(tree)})
    return tree[:max_chars] + ("\n...[truncated]" if len(tree) > max_chars else "")


@mcp.tool()
def execute(code: str) -> str:
    """Run Python on the desktop with `pyautogui` and `time` already imported, e.g.
    "pyautogui.click(960, 540)" or "pyautogui.hotkey('ctrl', 'l'); pyautogui.typewrite('hi')".
    Returns the command's output/errors."""
    ctl = _controller()
    payload = {"command": ["python", "-c", PYAUTOGUI_PKGS_PREFIX.format(command=code)], "shell": False}
    r = requests.post(ctl.http_server + "/execute", json=payload, timeout=120)
    _log({"tool": "execute", "code": code, "status": r.status_code})
    return r.text[:4000]


@mcp.tool()
def done(status: str = "DONE") -> str:
    """Call exactly once when finished: "DONE" if the task is complete, "FAIL" if it is
    impossible/infeasible as stated."""
    status = "FAIL" if status.strip().upper() == "FAIL" else "DONE"
    Path(_state()["done_file"]).write_text(status)
    _log({"tool": "done", "status": status})
    return f"recorded {status}"


if __name__ == "__main__":
    mcp.run()
