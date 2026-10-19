#!/usr/bin/env bash
# Fetch and build the benchmarks into vendor/ (pinned commits).
#   ./setup.sh            MiniWoB++ + WebGames
#   ./setup.sh webgames   just WebGames
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p vendor

MINIWOB_COMMIT=33c3b4ddef8c6eb67c57a29663d844b1eda7e614
WEBGAMES_COMMIT=309866f64642b864414ca2c7ff956e59e01d3317

fetch() {  # fetch <dir> <url> <commit>
    if [ ! -d "vendor/$1/.git" ]; then
        git clone --quiet "$2" "vendor/$1"
    fi
    git -C "vendor/$1" fetch --quiet --depth 1 origin "$3" 2>/dev/null || true
    git -C "vendor/$1" -c advice.detachedHead=false checkout --quiet "$3"
    echo "✓ $1 @ ${3:0:12}"
}

miniwob() {
    fetch miniwob-plusplus https://github.com/Farama-Foundation/miniwob-plusplus.git "$MINIWOB_COMMIT"
}

webgames() {
    fetch webgames https://github.com/convergence-ai/webgames.git "$WEBGAMES_COMMIT"
    (
        cd vendor/webgames/webgames
        # Pinned pnpm via npx: the lockfile is v9 and a system corepack shim may be broken.
        npx --yes pnpm@9.15.9 install --frozen-lockfile --ignore-scripts
        # `pnpm build` also runs tsc; type-checking is not needed to serve the app.
        npx --no-install vite build
    )
    test -f vendor/webgames/webgames/dist/index.html
    echo "✓ webgames built -> vendor/webgames/webgames/dist"
}

case "${1:-all}" in
    all) miniwob; webgames ;;
    miniwob) miniwob ;;
    webgames) webgames ;;
    *) echo "usage: $0 [all|miniwob|webgames]" >&2; exit 2 ;;
esac
