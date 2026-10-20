"""Run a benchmark suite against one harness.

    ./bench.sh --harness hermes --suite miniwob-quick
    ./bench.sh --harness hermes --suite webgames-quick --trials 3
    ./bench.sh --harness noop --suite webgames-all      # plumbing check, no agent

Each attempt gets its own empty working directory and a unique run token. Results go to
runs/<timestamp>-<harness>-<suite>/results.jsonl (one line per attempt) and a summary is
printed at the end (see report.py).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import tempfile
import time
from datetime import datetime
from pathlib import Path

from bench import adapters, report, server
from bench.tasks import MINIWOB_HTML, MINIWOB_PROMPT, ROOT, WEBGAMES_DIST, WEBGAMES_PROMPT, load_suite

# Tool inputs that suggest the agent read or poked page internals instead of using the UI.
# JavaScript on the page's elements (clicks, events, input values) is fine; reading the app's
# source, React internals (component state, function source) or MiniWoB's task code is not.
SUSPECT = re.compile(r"WOB_|core\.endEpisode|startEpisodeReal|genProblem|/assets/[^\"']*\.js|\"password\"\s*:"
                     r"|__react|_reactRootContainer|memoized(State|Props)")
# Local files: only the browser's own downloads (a task can hand the agent a file) may be opened.
FILE_URL = re.compile(r"file://(/[^\"'\s]*)")
DOWNLOAD_DIRS = ("/tmp/hb-playwright-out/",)


def suspect(tool_input: str) -> bool:
    if SUSPECT.search(tool_input):
        return True
    return any(not os.path.normpath(p).startswith(DOWNLOAD_DIRS) for p in FILE_URL.findall(tool_input))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--harness", required=True, help="adapter module in bench/adapters (hermes, noop)")
    ap.add_argument("--suite", required=True)
    ap.add_argument("--tasks", help="comma-separated task ids to run (subset of the suite)")
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--budget", type=int, default=240, help="per-attempt wall-clock budget, seconds")
    ap.add_argument("--model", help="model override passed to the adapter")
    ap.add_argument("--out", help="output directory (default runs/<stamp>-<harness>-<suite>)")
    args = ap.parse_args(argv)

    tasks = load_suite(args.suite, args.tasks.split(",") if args.tasks else None)
    adapter = adapters.load(args.harness)
    out = Path(args.out) if args.out else ROOT / "runs" / f"{datetime.now():%Y%m%d-%H%M%S}-{args.harness}-{args.suite}"
    out.mkdir(parents=True, exist_ok=True)
    mw_results = out / "miniwob_results"

    suites = {t.suite for t in tasks}
    mw = server.start_miniwob(MINIWOB_HTML, mw_results) if "miniwob" in suites else None
    wg = server.start_webgames(WEBGAMES_DIST) if "webgames" in suites else None

    harness_version = adapter.version() if hasattr(adapter, "version") else None
    (out / "config.json").write_text(json.dumps({**vars(args), "harness_version": harness_version, "n_tasks": len(tasks),
                                                 "started": datetime.now().isoformat()}, indent=2))
    results_path = out / "results.jsonl"
    total = len(tasks) * args.trials
    n = 0
    for trial in range(args.trials):
        for task in tasks:
            n += 1
            token = secrets.token_hex(6)
            if task.suite == "miniwob":
                url = (f"http://127.0.0.1:{mw.server_port}/miniwob/{task.id}.html"
                       f"?bench_run={token}&seed={trial}")
                prompt = MINIWOB_PROMPT.format(url=url)
            else:
                url = f"http://127.0.0.1:{wg.server_port}/{task.meta['path']}"
                prompt = WEBGAMES_PROMPT.format(url=url)

            attempt_dir = out / "attempts" / f"{task.suite}__{task.id}__t{trial}"
            attempt_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="hb-work-") as work:
                res = adapter.run(prompt, Path(work), attempt_dir, args.budget, model=args.model)

            row = {"suite": task.suite, "task": task.id, "trial": trial, "token": token,
                   "harness": args.harness, "model": args.model, "url": url, **grade(task, token, res, mw_results)}
            row.update({k: v for k, v in res.items() if k != "tool_inputs"})
            row["model"] = res.get("model") or args.model
            row["suspect"] = any(suspect(s) for s in res.get("tool_inputs", []))
            if task.suite == "webgames":
                row.update(difficulty=task.meta.get("difficulty"), variant=task.meta.get("variant"),
                           tags=task.meta.get("tags"))
            with results_path.open("a") as f:
                f.write(json.dumps(row) + "\n")
            mark = "PASS" if row["success"] else "fail"
            print(f"[{n}/{total}] {mark} {task.suite}/{task.id} t{trial} "
                  f"{row['wall_s']}s tools={row['tool_calls']} tok={row.get('tokens_total')}"
                  f"{' SUSPECT' if row['suspect'] else ''}", flush=True)

    print()
    print(report.summarize([json.loads(l) for l in results_path.read_text().splitlines()]))
    print(f"\nresults: {results_path}")


def grade(task, token, res, mw_results: Path) -> dict:
    if task.suite == "miniwob":
        f = mw_results / f"{token}.json"
        if not f.exists():
            return {"success": False, "score": 0.0, "detail": "no episode result recorded"}
        r = json.loads(f.read_text())
        raw = float(r.get("raw_reward") or 0)
        # BrowserGym convention: success iff the raw (time-independent) reward is positive.
        return {"success": raw > 0, "score": raw, "detail": r.get("reason")}
    password = task.meta["password"]
    ok = password in (res.get("final_text") or "")  # WebGames' own scorer: substring match
    return {"success": ok, "score": float(ok), "detail": None if ok else "password not in final answer"}


if __name__ == "__main__":
    main()
