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
    """Success rate per suite, then a task-by-task grid, one column per harness/model."""
    whos = sorted({_who(r) for r in rows})
    suites = sorted({r["suite"] for r in rows})
    lines = ["| suite | " + " | ".join(whos) + " |", "|---|" + "---|" * len(whos)]
    for s in suites:
        cells = []
        for w in whos:
            rs = [r for r in rows if r["suite"] == s and _who(r) == w]
            ok = sum(passed(r) for r in rs)
            cells.append(f"{ok}/{len(rs)} ({100 * ok / len(rs):.0f}%)" if rs else "-")
        lines.append(f"| {s} | " + " | ".join(cells) + " |")
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
