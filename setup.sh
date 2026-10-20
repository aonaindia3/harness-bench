#!/usr/bin/env bash
# Fetch and build the benchmarks into vendor/ (pinned commits).
#   ./setup.sh            MiniWoB++ + WebGames
#   ./setup.sh webgames   just WebGames
#   ./setup.sh playwright Playwright MCP (for the hermes_playwright adapter)
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

OSWORLD_COMMIT=a0b463f88cadaf2729a086f049d217d3e9a64b05
UV="${UV:-$(command -v uv || echo "$HOME/.hermes/tools/uv-0.12.3-linux-x64/uv")}"

osworld() {  # ~15 GB: Python env, the osworld-docker image and the Ubuntu VM disk
    fetch OSWorld https://github.com/xlang-ai/OSWorld.git "$OSWORLD_COMMIT"
    (
        cd vendor/OSWorld
        [ -x .venv/bin/python ] || "$UV" venv --quiet --python 3.10 .venv
        # CPU-only torch/torchvision: the evaluators don't need CUDA and it saves ~2.5 GB.
        # Installed again after requirements.txt, which otherwise pulls a mismatched torchvision.
        cpu_torch=(--index-url https://download.pytorch.org/whl/cpu "torch==2.5.1" "torchvision==0.20.1")
        "$UV" pip install --quiet --python .venv/bin/python "${cpu_torch[@]}"
        "$UV" pip install --quiet --python .venv/bin/python -r requirements.txt "mcp>=1.2,<2"
        "$UV" pip install --quiet --python .venv/bin/python --reinstall-package torchvision "${cpu_torch[@]}"
        docker pull --quiet happysixd/osworld-docker
        .venv/bin/python -c "
import os
from desktop_env.providers.docker.manager import VMS_DIR, _download_vm
if not os.path.exists(os.path.join(VMS_DIR, 'Ubuntu.qcow2')):
    _download_vm(VMS_DIR)
print('VM image:', os.path.abspath(os.path.join(VMS_DIR, 'Ubuntu.qcow2')))"
    )
    echo "✓ OSWorld ready (vendor/OSWorld)"
}

PLAYWRIGHT_MCP_VERSION=0.0.83

playwright() {  # Playwright MCP browser server, for the hermes_playwright adapter
    npm install --silent --no-audit --no-fund --prefix vendor/playwright-mcp "@playwright/mcp@$PLAYWRIGHT_MCP_VERSION"
    node vendor/playwright-mcp/node_modules/@playwright/mcp/cli.js --version
    echo "✓ playwright-mcp $PLAYWRIGHT_MCP_VERSION -> vendor/playwright-mcp"
}

case "${1:-all}" in
    all) miniwob; webgames ;;
    miniwob) miniwob ;;
    webgames) webgames ;;
    osworld) osworld ;;
    playwright) playwright ;;
    *) echo "usage: $0 [all|miniwob|webgames|osworld|playwright]" >&2; exit 2 ;;
esac
