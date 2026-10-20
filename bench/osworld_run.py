"""Run OSWorld tasks against Hermes (run with vendor/OSWorld/.venv/bin/python, via ./bench.sh osworld).

    ./bench.sh osworld --tasks-file test_small.json [--domain os] [--limit 5] [--max-steps 50]

Per task: DesktopEnv.reset(task) -> Hermes drives the VM through bench/osworld_mcp.py ->
DesktopEnv.evaluate(). Rows use the same results.jsonl schema as bench/run.py. Each task's screen
is recorded to attempts/<task>/recording.mp4 (OSWorld's own recorder; --no-record turns it off).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OSW = ROOT / "vendor" / "OSWorld"
sys.path[:0] = [str(OSW), str(ROOT)]
os.chdir(OSW)  # DesktopEnv resolves ./docker_vm_data and ./cache relative to cwd

from desktop_env.desktop_env import DesktopEnv  # noqa: E402

from bench.adapters.hermes import HERMES, parse_transcript, version  # noqa: E402
from bench.report import summarize  # noqa: E402

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks-file", default="test_small.json")
    ap.add_argument("--domain")
    ap.add_argument("--ids", help="comma-separated task ids")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--max-steps", type=int, default=50, help="Hermes --max-turns (tool iterations)")
    ap.add_argument("--budget", type=int, default=900, help="per-task wall-clock budget, seconds")
    ap.add_argument("--include-gdrive", action="store_true", help="needs Google Drive client secrets")
    ap.add_argument("--out", help="output dir; re-using one resumes it (finished tasks are skipped)")
    ap.add_argument("--no-record", action="store_true", help="don't save a screen recording per task")
    args = ap.parse_args()

    examples = load_examples(args.tasks_file, args.domain, args.limit,
                             args.ids.split(",") if args.ids else None, args.include_gdrive)
    # cwd is vendor/OSWorld by now, so a relative --out is taken relative to the repo root; the MCP
    # server runs elsewhere and needs absolute paths in the state file.
    out = ROOT / args.out if args.out else ROOT / "runs" / f"{datetime.now():%Y%m%d-%H%M%S}-hermes-osworld"
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps({**vars(args), "suite": "osworld", "harness": "hermes",
                                                 "harness_version": version(), "n_tasks": len(examples)}, indent=2))
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
            attempt.mkdir(parents=True, exist_ok=True)
            try:
                env.reset(task_config=ex)
            except Exception as e:  # a task whose setup can't run counts as a failure, not a crash
                row = {"suite": "osworld", "task": f"{dom}/{ex['id']}", "trial": 0, "harness": "hermes",
                       "model": None, "success": False, "score": 0.0, "detail": f"setup failed: {e}"[:500],
                       "wall_s": 0.0, "exit_code": None, "timed_out": False, "instruction": ex["instruction"],
                       "final_text": "", "tool_calls": 0, "tools": {}, "tokens_total": None}
                with results_path.open("a") as f:
                    f.write(json.dumps(row) + "\n")
                print(f"[{i}/{len(examples)}] fail {row['task']} ({row['detail'][:120]})", flush=True)
                continue
            time.sleep(60)  # same settle time as OSWorld's lib_run_single
            recording = not args.no_record and _try(env.controller.start_recording)
            done_file = attempt / "done.txt"
            STATE.write_text(json.dumps({"vm_ip": env.vm_ip, "server_port": env.server_port,
                                         "done_file": str(done_file), "action_log": str(attempt / "actions.jsonl")}))
            cmd = [HERMES, "-p", PROFILE, "chat", "-q", PROMPT.format(instruction=ex["instruction"]),
                   "--format", "stream-json", "-t", "osworld", "--ignore-rules", "--source", "tool",
                   "--run-budget", str(args.budget), "--max-turns", str(args.max_steps)]
            t0 = time.monotonic()
            timed_out = False
            with (attempt / "transcript.jsonl").open("w") as so, (attempt / "stderr.log").open("w") as se:
                proc = subprocess.Popen(cmd, cwd=attempt, stdout=so, stderr=se, stdin=subprocess.DEVNULL)
                try:
                    proc.wait(timeout=args.budget + 120)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    proc.kill()
                    proc.wait()
            wall = time.monotonic() - t0
            status = done_file.read_text().strip() if done_file.exists() else None
            env.step("FAIL" if status == "FAIL" else "DONE", pause=0)
            if recording:
                _try(lambda: env.controller.end_recording(str(attempt / "recording.mp4")))
            time.sleep(20)  # OSWorld's settle time before evaluation
            try:
                score, err = float(env.evaluate()), None
            except Exception as e:  # evaluator crashes count as failures, but are reported
                score, err = 0.0, f"evaluate error: {e}"
            res = parse_transcript(attempt / "transcript.jsonl")
            res.pop("tool_inputs", None)
            row = {"suite": "osworld", "task": f"{dom}/{ex['id']}", "trial": 0, "harness": "hermes",
                   "model": None, "success": score >= 1.0, "score": score,
                   "detail": err or (f"agent said {status}" if status else "agent never called done"),
                   "wall_s": round(wall, 1), "exit_code": proc.returncode, "timed_out": timed_out,
                   "instruction": ex["instruction"], **res}
            with results_path.open("a") as f:
                f.write(json.dumps(row) + "\n")
            print(f"[{i}/{len(examples)}] {'PASS' if row['success'] else 'fail'} {row['task']} score={score} "
                  f"{row['wall_s']}s tools={row['tool_calls']} ({row['detail']})", flush=True)
    finally:
        env.close()

    rows = [json.loads(l) for l in results_path.read_text().splitlines()]
    print()
    print(summarize(rows))
    print(f"\nresults: {results_path}")


if __name__ == "__main__":
    main()
