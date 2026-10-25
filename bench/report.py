"""Summaries over results.jsonl files.

    python3 -m bench.report runs/*/results.jsonl            # summary + per-task table
    python3 -m bench.report --compare results/*/*/results.jsonl   # harnesses side by side
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return statistics.mean(xs) if xs else None


def _fmt(x, nd=0):
    return "-" if x is None else f"{x:,.{nd}f}"


def passed(r: dict) -> bool:
    """A pass only counts if the agent didn't reach into page internals to get it."""
    return bool(r["success"]) and not r.get("suspect")


ENDINGS = ("done", "fail", "steps", "time", "safety", "error", "none", "env")


def ended(r: dict) -> str:
    """How an OSWorld attempt ended (one of ENDINGS): what the agent declared with done, or why it
    stopped without declaring. Works on rows from before the field existed (it is derived from
    detail, timed_out and exit_code, which every row has)."""
    d = r.get("detail") or ""
    if d.startswith(("setup failed", "evaluate error")):
        return "env"  # OSWorld's own setup or evaluation broke, not the agent
    if d.startswith("agent said "):
        return d.removeprefix("agent said ").lower()  # done / fail
    if r.get("safety_check"):
        return "safety"
    if r.get("timed_out"):
        return "time"
    if r.get("steps_exhausted"):
        return "steps"
    return "error" if r.get("exit_code") else "none"


def _trials(rs: list[dict]) -> str:
    """'6, 8, 7 of 36 · mean 7.0' over trials, or '' for a single trial."""
    by_trial = defaultdict(list)
    for r in rs:
        by_trial[r.get("trial", 0)].append(r)
    if len(by_trial) < 2:
        return ""
    oks = [sum(passed(r) for r in by_trial[t]) for t in sorted(by_trial)]
    sizes = {len(v) for v in by_trial.values()}
    of = f" of {sizes.pop()}" if len(sizes) == 1 else ""
    return f"{', '.join(map(str, oks))}{of} · mean {statistics.mean(oks):.1f}"


def summarize(rows: list[dict]) -> str:
    groups = defaultdict(list)
    for r in rows:
        groups[(r.get("_run") or r["harness"], r.get("model") or "default", r["suite"])].append(r)
    lines = ["| harness | model | suite | attempts | success | mean time (s) | median time (s) "
             "| mean tool calls | mean tokens | timeouts | suspect |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for (h, m, s), rs in sorted(groups.items()):
        ok = sum(passed(r) for r in rs)
        times = [r["wall_s"] for r in rs]
        lines.append(
            f"| {h} | {m} | {s} | {len(rs)} | {ok}/{len(rs)} ({100 * ok / len(rs):.0f}%) "
            f"| {_fmt(_mean(times), 1)} | {_fmt(statistics.median(times), 1)} "
            f"| {_fmt(_mean([r['tool_calls'] for r in rs]), 1)} | {_fmt(_mean([r.get('tokens_total') for r in rs]))} "
            f"| {sum(bool(r.get('timed_out')) for r in rs)} | {sum(bool(r.get('suspect')) for r in rs)} |")
    return "\n".join(lines)


def per_task(rows: list[dict]) -> str:
    lines = ["| suite | task | result | score | time (s) | tool calls | tokens | note |",
             "|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["suite"], r["task"], r["trial"])):
        note = r.get("detail") or ""
        if r.get("timed_out"):
            note = "timed out"
        if r.get("suspect"):
            note = (note + "; " if note else "") + "suspect: touched page internals"
        lines.append(f"| {r['suite']} | {r['task']} | {'PASS' if passed(r) else 'fail'} | {r.get('score', 0):.2f} "
                     f"| {r['wall_s']} | {r['tool_calls']} | {_fmt(r.get('tokens_total'))} | {note} |")
    return "\n".join(lines)


def _who(r: dict) -> str:
    # Rows read from results/<name>/<suite>/ are labelled by <name>, so two runs of the same
    # harness and model (e.g. a replication) stay separate columns.
    return r.get("_run") or f"{r['harness']} / {r.get('model') or 'default'}"


def compare(rows: list[dict]) -> str:
    """Success rate per suite (per trial when there are several), how OSWorld attempts ended, then
    a task-by-task grid, one column per harness/model."""
    whos = sorted({_who(r) for r in rows})
    suites = sorted({r["suite"] for r in rows})
    lines = ["| suite | " + " | ".join(whos) + " |", "|---|" + "---|" * len(whos)]
    for s in suites:
        cells = []
        for w in whos:
            rs = [r for r in rows if r["suite"] == s and _who(r) == w]
            ok = sum(passed(r) for r in rs)
            trials = _trials(rs)
            cells.append(f"{ok}/{len(rs)} ({100 * ok / len(rs):.0f}%)" + (f"; per trial {trials}" if trials else "")
                         if rs else "-")
        lines.append(f"| {s} | " + " | ".join(cells) + " |")
    # Only OSWorld has an explicit done step, so only its endings say something.
    osw = [r for r in rows if r["suite"] == "osworld"]
    for e in ENDINGS if osw else ():
        counts = [sum(ended(r) == e for r in osw if _who(r) == w) for w in whos]
        if any(counts):
            lines.append(f"| osworld ended: {e} | " + " | ".join(map(str, counts)) + " |")
    if osw:  # the agent's own check said complete, the evaluator disagreed
        counts = [sum(ended(r) == "done" and not passed(r) for r in osw if _who(r) == w) for w in whos]
        lines.append("| osworld said done, failed | " + " | ".join(map(str, counts)) + " |")
    lines += ["", "| suite | task | " + " | ".join(whos) + " |", "|---|---|" + "---|" * len(whos)]
    tasks = sorted({(r["suite"], r["task"]) for r in rows})
    for s, t in tasks:
        cells = []
        for w in whos:
            rs = [r for r in rows if r["suite"] == s and r["task"] == t and _who(r) == w]
            ok = sum(passed(r) for r in rs)
            cell = "-" if not rs else ("PASS" if ok == len(rs) else "fail" if ok == 0 else f"{ok}/{len(rs)}")
            if any(r.get("suspect") for r in rs):
                cell += " (suspect)"
            cells.append(cell)
        lines.append(f"| {s} | {t} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    args = sys.argv[1:]
    mode = args.pop(0) if args and args[0] == "--compare" else None
    rows = []
    for p in args:
        run = Path(p).parent.parent
        for l in open(p):
            if l.strip():
                rows.append({**json.loads(l), **({"_run": run.name} if run.parent.name == "results" else {})})
    if mode:
        print(compare(rows))
    else:
        print(summarize(rows))
        print()
        print(per_task(rows))
