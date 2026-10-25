"""Run OSWorld tasks against a harness (run with vendor/OSWorld/.venv/bin/python, via ./bench.sh osworld).

    ./bench.sh osworld --tasks-file test_small.json [--domain os] [--limit 5] [--max-steps 50]
    ./bench.sh osworld --harness openai_cua ...      # OpenAI computer-use agent (needs OPENAI_API_KEY)
    ./bench.sh osworld --harness openai_fn ...       # same agent, actions as a plain function tool
    ./bench.sh osworld --trial 1 ...                 # another trial: rows say trial 1, out dir ends -t1

Per task: DesktopEnv.reset(task) -> the harness drives the VM -> DesktopEnv.evaluate(). Hermes
uses the tools in bench/osworld_mcp.py; openai_cua / openai_fn (bench/cua/osworld_agent.py) send
the model's actions as pyautogui code through the same controller. Harnesses are entries in
HARNESSES. Rows use the same results.jsonl schema as bench/run.py, plus `ended` (how the attempt
ended, see bench.report.ended). Each task's screen is recorded to attempts/<task>/recording.mp4
(OSWorld's own recorder; --no-record turns it off).

An attempt that ends on a usage limit (bench.limits) gets no row: the run stops with exit code 75,
and re-running with the same --out resumes from that task.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
OSW = ROOT / "vendor" / "OSWorld"
sys.path[:0] = [str(OSW), str(ROOT)]
os.chdir(OSW)  # DesktopEnv resolves ./docker_vm_data and ./cache relative to cwd

from desktop_env.desktop_env import DesktopEnv  # noqa: E402

from bench import limits  # noqa: E402
from bench.adapters import hermes  # noqa: E402
from bench.cua import osworld_agent  # noqa: E402
from bench.report import ended, summarize  # noqa: E402

STATE = ROOT / "runs" / ".osworld_current.json"
PROFILE = os.environ.get("HERMES_OSWORLD_PROFILE", "bench-osworld")

PROMPT = (
    "You are operating an Ubuntu desktop (1920x1080) through the osworld tools: screenshot, "
    "accessibility_tree, execute (Python with pyautogui) and done. The user's password is "
    "'password' if anything asks for it.\n\nTask: {instruction}\n\n"
    "Work step by step: look at the screen, act, then check the result. When the task is "
    "complete call done(\"DONE\"); if it cannot be done as stated call done(\"FAIL\")."
)


def _try(fn) -> bool:
    """Recording is a convenience: a recorder failure is logged, never fails the task."""
    try:
        fn()
        return True
    except Exception as e:
        print(f"recording error: {e}", flush=True)
        return False


def needs_gdrive(ex: dict) -> bool:
    return "googledrive" in json.dumps(ex.get("config", [])) + json.dumps(ex.get("evaluator", {}))


def load_examples(tasks_file: str, domain: str | None, limit: int | None, ids: list[str] | None,
                  include_gdrive: bool):
    meta = json.loads((OSW / "evaluation_examples" / tasks_file).read_text())
    out = []
    for dom, task_ids in meta.items():
        if domain and dom != domain:
            continue
        for tid in task_ids:
            if ids and tid not in ids:
                continue
            ex = json.loads((OSW / "evaluation_examples" / "examples" / dom / f"{tid}.json").read_text())
            # Google Drive tasks need OAuth client secrets OSWorld doesn't ship (cf. test_nogdrive.json).
            if needs_gdrive(ex) and not include_gdrive:
                print(f"skip (needs Google Drive credentials): {dom}/{tid}")
                continue
            out.append((dom, ex))
    return out[:limit] if limit else out


def run_hermes(ex: dict, attempt: Path, env, args) -> dict:
    STATE.write_text(json.dumps({"vm_ip": env.vm_ip, "server_port": env.server_port,
                                 "done_file": str(attempt / "done.txt"), "action_log": str(attempt / "actions.jsonl")}))
    cmd = [hermes.HERMES, "-p", PROFILE, "chat", "-q", PROMPT.format(instruction=ex["instruction"]),
           "--format", "stream-json", "-t", "osworld", "--ignore-rules", "--source", "tool",
           "--run-budget", str(args.budget), "--max-turns", str(args.max_steps)]
    timed_out = False
    with (attempt / "transcript.jsonl").open("w") as so, (attempt / "stderr.log").open("w") as se:
        proc = subprocess.Popen(cmd, cwd=attempt, stdout=so, stderr=se, stdin=subprocess.DEVNULL)
        try:
            proc.wait(timeout=args.budget + 120)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            proc.wait()
    # Hermes exits 1 when --max-turns runs out; it reports nothing more specific.
    calls = hermes.parse_transcript(attempt / "transcript.jsonl")["tool_calls"]
    return {"exit_code": proc.returncode, "timed_out": timed_out,
            "steps_exhausted": proc.returncode == 1 and calls >= args.max_steps}


def run_cua(ex: dict, attempt: Path, env, args, native: bool) -> dict:
    return osworld_agent.run(env.controller, ex["instruction"], attempt, args.budget, args.max_steps, native=native)


def cua_version(native: bool) -> str:
    tool = "computer tool" if native else "actions as a function tool"
    return f"bench/cua/osworld_agent.py (Responses API, {tool}, {osworld_agent.MODEL}, effort {osworld_agent.EFFORT})"


@dataclass
class Harness:
    """run(ex, attempt, env, args) drives the VM for one task and returns exit_code and timed_out
    (optionally steps_exhausted, safety_check); it writes attempt/transcript.jsonl, and
    attempt/done.txt with DONE or FAIL if the agent declared either. parse(transcript) returns
    the bench.adapters result fields."""
    run: Callable[..., dict]
    version: Callable[[], str | None]
    parse: Callable[[Path], dict]
    needs_env: str | None = None


HARNESSES = {
    "hermes": Harness(run_hermes, hermes.version, hermes.parse_transcript),
    "openai_cua": Harness(partial(run_cua, native=True), partial(cua_version, True),
                          osworld_agent.parse_transcript, "OPENAI_API_KEY"),
    "openai_fn": Harness(partial(run_cua, native=False), partial(cua_version, False),
                         osworld_agent.parse_transcript, "OPENAI_API_KEY"),
}


def append_row(path: Path, row: dict) -> None:
    row["ended"] = ended(row)
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks-file", default="test_small.json")
    ap.add_argument("--domain")
    ap.add_argument("--ids", help="comma-separated task ids")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--harness", choices=sorted(HARNESSES), default="hermes")
    ap.add_argument("--trial", type=int, default=0, help="trial number written to each row")
    ap.add_argument("--max-steps", type=int, default=50,
                    help="tool iterations (Hermes --max-turns; openai_cua: computer-tool turns)")
    ap.add_argument("--budget", type=int, default=900, help="per-task wall-clock budget, seconds")
    ap.add_argument("--include-gdrive", action="store_true", help="needs Google Drive client secrets")
    ap.add_argument("--out", help="output dir; re-using one resumes it (finished tasks are skipped)")
    ap.add_argument("--no-record", action="store_true", help="don't save a screen recording per task")
    args = ap.parse_args()

    examples = load_examples(args.tasks_file, args.domain, args.limit,
                             args.ids.split(",") if args.ids else None, args.include_gdrive)
    # cwd is vendor/OSWorld by now, so a relative --out is taken relative to the repo root; the MCP
    # server runs elsewhere and needs absolute paths in the state file.
    out = ROOT / args.out if args.out else (
        ROOT / "runs" / f"{datetime.now():%Y%m%d-%H%M%S}-{args.harness}-osworld-t{args.trial}")
    out.mkdir(parents=True, exist_ok=True)
    harness = HARNESSES[args.harness]
    if harness.needs_env and not os.environ.get(harness.needs_env):
        raise SystemExit(f"{args.harness} needs {harness.needs_env}")
    (out / "config.json").write_text(json.dumps({**vars(args), "suite": "osworld", "harness_version": harness.version(),
                                                 "n_tasks": len(examples)}, indent=2))
    results_path = out / "results.jsonl"
    if results_path.exists():
        finished = {json.loads(l)["task"] for l in results_path.read_text().splitlines() if l.strip()}
        examples = [(d, ex) for d, ex in examples if f"{d}/{ex['id']}" not in finished]
        print(f"resuming: {len(finished)} finished, {len(examples)} to go")

    env = DesktopEnv(provider_name="docker", os_type="Ubuntu", action_space="pyautogui",
                     headless=True, require_a11y_tree=False)
    try:
        for i, (dom, ex) in enumerate(examples, 1):
            attempt = out / "attempts" / f"{dom}__{ex['id']}"
            # Finished tasks were skipped above, so anything here is from an attempt that never got a
            # row (usage limit, Ctrl-C): start clean so its screenshots and action log don't mix in.
            shutil.rmtree(attempt, ignore_errors=True)
            attempt.mkdir(parents=True)
            task = f"{dom}/{ex['id']}"
            try:
                env.reset(task_config=ex)
            except Exception as e:  # a task whose setup can't run counts as a failure, not a crash
                row = {"suite": "osworld", "task": task, "trial": args.trial, "harness": args.harness,
                       "model": None, "success": False, "score": 0.0, "detail": f"setup failed: {e}"[:500],
                       "wall_s": 0.0, "exit_code": None, "timed_out": False, "instruction": ex["instruction"],
                       "final_text": "", "tool_calls": 0, "tools": {}, "tokens_total": None}
                append_row(results_path, row)
                print(f"[{i}/{len(examples)}] fail {task} ({row['detail'][:120]})", flush=True)
                continue
            time.sleep(60)  # same settle time as OSWorld's lib_run_single
            recording = not args.no_record and _try(env.controller.start_recording)
            done_file = attempt / "done.txt"
            t0 = time.monotonic()
            agent = harness.run(ex, attempt, env, args)
            wall = time.monotonic() - t0
            limit = limits.limited(attempt, agent["exit_code"])
            if limit:
                if recording:
                    _try(lambda: env.controller.end_recording(str(attempt / "recording.mp4")))
                (attempt / "limited.txt").write_text(limit + "\n")
                print(f"[{i}/{len(examples)}] usage limit on {task}, not scored: {limit[:200]}", flush=True)
                print(f"stopping; resume with the same --out: {out.relative_to(ROOT)}", flush=True)
                raise SystemExit(limits.EXIT_LIMITED)
            status = done_file.read_text().strip() if done_file.exists() else None
            env.step("FAIL" if status == "FAIL" else "DONE", pause=0)
            if recording:
                _try(lambda: env.controller.end_recording(str(attempt / "recording.mp4")))
            time.sleep(20)  # OSWorld's settle time before evaluation
            try:
                score, err = float(env.evaluate()), None
            except Exception as e:  # evaluator crashes count as failures, but are reported
                score, err = 0.0, f"evaluate error: {e}"
            res = harness.parse(attempt / "transcript.jsonl")
            res.pop("tool_inputs", None)
            row = {"suite": "osworld", "task": task, "trial": args.trial, "harness": args.harness,
                   "model": None, "success": score >= 1.0, "score": score,
                   "detail": err or (f"agent said {status}" if status else "agent never called done"),
                   "wall_s": round(wall, 1), "exit_code": agent["exit_code"], "timed_out": agent["timed_out"],
                   "steps_exhausted": agent.get("steps_exhausted", False),
                   "safety_check": agent.get("safety_check", False),
                   "instruction": ex["instruction"], **res}
            append_row(results_path, row)
            served = row.get("served_model")
            if served and row["model"] and not served.startswith(row["model"]):
                print(f"WARNING: asked for {row['model']}, the API served {served}", flush=True)
            print(f"[{i}/{len(examples)}] {'PASS' if row['success'] else 'fail'} {task} score={score} "
                  f"{row['wall_s']}s tools={row['tool_calls']} ({row['detail']}; ended {row['ended']})", flush=True)
    finally:
        env.close()

    rows = [json.loads(l) for l in results_path.read_text().splitlines()]
    print()
    print(summarize(rows))
    print(f"\nresults: {results_path}")


if __name__ == "__main__":
    main()
