"""Task lists and prompts for each suite.

Prompts follow each benchmark's own protocol where one exists:
- WebGames: the exact template from vendor/webgames/evals (password must appear in the final answer).
- MiniWoB++: BrowserGym-style -- the goal is the instruction rendered on the page.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
MINIWOB_HTML = VENDOR / "miniwob-plusplus" / "miniwob" / "html"
WEBGAMES_DIST = VENDOR / "webgames" / "webgames" / "dist"
WEBGAMES_TASKS = VENDOR / "webgames" / "evals" / "browseruse_webgames" / "webgames_tasks.jsonl"

QUICK_SIZE = 25
QUICK_SEED = 20261019  # fixed so every harness gets the same "quick" sample

# Not part of the BrowserGym MiniWoB++ task set (debug/human-only pages).
MINIWOB_EXCLUDE = {"click-test-transfer", "click-checkboxes-transfer"}

MINIWOB_PROMPT = (
    "Open {url} in the browser. The page shows a task instruction in the box at the top. "
    "Complete that task by interacting with the page the way a person would (clicking, typing, "
    "dragging, scrolling). Do not call the page's own JavaScript functions or read its internal "
    "variables. The task can only be attempted once. When you are finished, reply DONE."
)

WEBGAMES_PROMPT = (
    "go to {url} and complete the challenge as described. On successful completion, the task "
    "will give you a password. Tell me what the password is."
)


@dataclass
class Task:
    suite: str
    id: str
    meta: dict = field(default_factory=dict)


def miniwob_tasks() -> list[Task]:
    names = sorted(p.stem for p in (MINIWOB_HTML / "miniwob").glob("*.html"))
    return [Task("miniwob", n) for n in names if n not in MINIWOB_EXCLUDE]


def webgames_tasks() -> list[Task]:
    rows = [json.loads(l) for l in WEBGAMES_TASKS.read_text().splitlines() if l.strip()]
    return [Task("webgames", r["id"], r) for r in rows]


def _quick(tasks: list[Task]) -> list[Task]:
    picked = random.Random(QUICK_SEED).sample(tasks, min(QUICK_SIZE, len(tasks)))
    return sorted(picked, key=lambda t: t.id)


SUITES = {
    "miniwob-all": miniwob_tasks,
    "miniwob-quick": lambda: _quick(miniwob_tasks()),
    "webgames-all": webgames_tasks,
    "webgames-base": lambda: [t for t in webgames_tasks() if t.meta.get("variant") == "base"],
    "webgames-quick": lambda: _quick([t for t in webgames_tasks() if t.meta.get("variant") == "base"]),
}


def load_suite(name: str, only: list[str] | None = None) -> list[Task]:
    if name not in SUITES:
        raise SystemExit(f"unknown suite {name!r}; choose from {', '.join(SUITES)}")
    tasks = SUITES[name]()
    if only:
        tasks = [t for t in tasks if t.id in set(only)]
    return tasks
