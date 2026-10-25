#!/usr/bin/env bash
# Run OSWorld jobs one after another (one VM at a time):
#   ./bench.sh osworld-queue hermes:1 openai_cua:1 openai_fn:0 [-- extra osworld_run.py args]
# Job <harness>:<trial> writes runs/osw-<harness>-t<trial>; re-using that dir resumes it. A job that
# stops on a usage limit (exit 75) is set aside, and so are that harness's later jobs in the same
# pass; after the list, set-aside jobs get one more pass. Any other failure stops the queue.
set -uo pipefail
cd "$(dirname "$0")/.."

jobs=() extra=()
while [ $# -gt 0 ]; do
    if [ "$1" = "--" ]; then shift; extra=("$@"); break; fi
    [[ "$1" =~ ^[a-z_]+:[0-9]+$ ]] || { echo "bad job '$1', expected <harness>:<trial>" >&2; exit 2; }
    jobs+=("$1"); shift
done
[ ${#jobs[@]} -gt 0 ] || { echo "usage: $0 <harness>:<trial> ... [-- osworld args]" >&2; exit 2; }

for pass in 1 2; do
    deferred=() limited_harnesses=" "
    for job in "${jobs[@]}"; do
        h=${job%%:*} t=${job##*:}
        if [[ "$limited_harnesses" == *" $h "* ]]; then deferred+=("$job"); continue; fi
        echo "=== $(date '+%F %T') $h trial $t (pass $pass)"
        ./bench.sh osworld --harness "$h" --trial "$t" --out "runs/osw-$h-t$t" "${extra[@]}"
        rc=$?
        if [ $rc -eq 75 ]; then
            deferred+=("$job") limited_harnesses+="$h "
        elif [ $rc -ne 0 ]; then
            echo "=== $job failed (exit $rc); stopping the queue" >&2
            exit $rc
        fi
    done
    if [ ${#deferred[@]} -eq 0 ]; then echo "=== $(date '+%F %T') all jobs done"; exit 0; fi
    jobs=("${deferred[@]}")
    echo "=== $(date '+%F %T') usage limit, not finished: ${jobs[*]}"
done
echo "=== rerun later with: ./bench.sh osworld-queue ${jobs[*]}" >&2
exit 75
