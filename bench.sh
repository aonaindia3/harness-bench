#!/usr/bin/env bash
# Run a benchmark suite: ./bench.sh --harness hermes --suite miniwob-quick [--trials N] [--tasks a,b]
# Report only:          ./bench.sh report runs/*/results.jsonl   (or: report --compare results/*/*/results.jsonl)
# Share a run:          ./bench.sh publish runs/<run>
set -euo pipefail
cd "$(dirname "$0")"
if [ "${1:-}" = "report" ]; then
    shift
    exec python3 -m bench.report "$@"
fi
if [ "${1:-}" = "publish" ]; then
    shift
    exec python3 -m bench.publish "$@"
fi
if [ "${1:-}" = "osworld" ]; then
    shift
    exec vendor/OSWorld/.venv/bin/python bench/osworld_run.py "$@"
fi
exec python3 -m bench.run "$@"
