"""Summaries over results.jsonl files.

    python3 -m bench.report runs/*/results.jsonl
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return statistics.mean(xs) if xs else None


def _fmt(x, nd=0):
    return "-" if x is None else f"{x:,.{nd}f}"


def summarize(rows: list[dict]) -> str:
    groups = defaultdict(list)
    for r in rows:
        groups[(r["harness"], r.get("model") or "default", r["suite"])].append(r)
    lines = ["| harness | model | suite | attempts | success | mean time (s) | median time (s) "
             "| mean tool calls | mean tokens | timeouts | suspect |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for (h, m, s), rs in sorted(groups.items()):
        ok = sum(r["success"] for r in rs)
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
        lines.append(f"| {r['suite']} | {r['task']} | {'PASS' if r['success'] else 'fail'} | {r.get('score', 0):.2f} "
                     f"| {r['wall_s']} | {r['tool_calls']} | {_fmt(r.get('tokens_total'))} | {note} |")
    return "\n".join(lines)


if __name__ == "__main__":
    rows = [json.loads(l) for p in sys.argv[1:] for l in open(p) if l.strip()]
    print(summarize(rows))
    print()
    print(per_task(rows))
