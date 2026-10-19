#!/usr/bin/env bash
# Run a benchmark suite: ./bench.sh --harness hermes --suite miniwob-quick [--trials N] [--tasks a,b]
# Report only:          ./bench.sh report runs/*/results.jsonl
set -euo pipefail
cd "$(dirname "$0")"
if [ "${1:-}" = "report" ]; then
    shift
    exec python3 -m bench.report "$@"
fi
exec python3 -m bench.run "$@"
