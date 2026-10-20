# harness-bench

Benchmarks agent **harnesses** (Hermes Agent first; others plug in as adapters) on standard
browser / desktop UI-driving benchmarks, scored by each benchmark's own checker.

| Suite | What it is | Scoring | Runs where |
|---|---|---|---|
| **MiniWoB++** (Farama, BrowserGym's web set) | 125 small synthetic web UI tasks: forms, date pickers, drag, menus, email UI, canvas | the page's own reward; success = raw reward > 0 (BrowserGym convention) | local static server |
| **WebGames** (Convergence, 2025) | 150 challenges (53 base + easy/hard variants) built to be easy for humans, hard for agents | password revealed on completion must appear in the final answer (the official scorer) | local build of the SPA |
| **OSWorld** (xlang-ai) | real Ubuntu desktop tasks (Chrome, LibreOffice, GIMP, VS Code, Thunderbird, VLC, OS) | OSWorld's own `DesktopEnv.evaluate()` | Docker + KVM VM |

Everything runs on this machine against localhost / a local VM. The agent's browser never
touches the public web or your own Chrome profile.

## Quick start

```bash
./setup.sh                 # MiniWoB++ + WebGames (pinned commits), builds WebGames
./setup.sh osworld         # optional, ~15 GB: OSWorld venv, docker image, Ubuntu VM disk

./bench.sh --harness noop   --suite miniwob-quick     # plumbing check, no agent
./bench.sh --harness hermes --suite miniwob-quick     # 25 tasks
./bench.sh --harness hermes --suite webgames-quick    # 25 base tasks
./bench.sh osworld --domain os --limit 2              # OSWorld via MCP
./bench.sh report runs/*/results.jsonl                # summary + per-task table
```

Suites: `miniwob-all`, `miniwob-quick`, `webgames-all`, `webgames-base`, `webgames-quick`
(`--tasks a,b` narrows any suite). "quick" = a fixed random sample of 25 (seed in
`bench/tasks.py`) so every harness gets the same tasks. Options: `--trials N`,
`--budget SECONDS` (default 240 per attempt), `--model`.

## What is measured (per attempt, in `runs/<run>/results.jsonl`)

success, score, wall time, tool calls (by tool), tokens (input/output/total/cache read),
timeout, the final answer, and a `suspect` flag when the agent's tool inputs touch page
internals (MiniWoB's `core.*`/`WOB_*`, the WebGames JS bundle, React component state or source)
instead of using the page.
The report counts a suspect pass as a failure.
Full transcripts are in `runs/<run>/attempts/<task>/transcript.jsonl`.

## Protocol notes

- **MiniWoB++**: `bench/miniwob_shim.js` is injected into each task page. It seeds the RNG
  (`task:trial`), lifts the 10 s episode limit (as BrowserGym does for LLM agents),
  auto-starts the episode and reports the first episode's reward to the local server.
  The agent reads the instruction from the page (BrowserGym puts the same text in the goal).
- **WebGames**: prompt is the template from `vendor/webgames/evals`, with the local URL, plus one
  sentence: console JavaScript on the page's elements is allowed, reading the site's source or
  internal app state (React internals) is not and counts as a failure.
  The JS bundle holds every password, so the local server only serves `.js` files to real
  `<script>` loads (`Sec-Fetch-Dest: script`); `fetch()` from the console or opening the file
  as a page gets a 403. (Added after Hermes read passwords out of the bundle in 6/25 attempts.)
- **OSWorld**: `bench/osworld_mcp.py` gives the harness four tools (screenshot,
  accessibility_tree, execute pyautogui code, done DONE/FAIL); `bench/osworld_run.py`
  resets the task, runs the harness, then calls OSWorld's evaluator. A `done("FAIL")` is
  passed to OSWorld as its FAIL action (that is how infeasible tasks are scored).
  Default 50 tool iterations and 900 s per task.

## Hermes setup

The Hermes adapter (`bench/adapters/hermes.py`) runs `hermes -p bench chat -q ... --format
stream-json -t browser --ignore-rules`, using a dedicated **`bench`** profile so the user's
default profile is untouched:

```bash
hermes profile create bench --clone-all --no-alias
hermes -p bench tools disable terminal file code_execution web vision image_gen tts skills \
    todo memory session_search connections clarify delegation cronjob computer_use
hermes -p bench config set browser.backend off
```

`browser.backend off` selects Hermes's built-in browser tools (agent-browser + headless
Chromium: navigate, snapshot, click, type, scroll, press, vision, console, ...). Hermes's
default Browser Use driver (`browser_exec`) is only offered to sessions that also have the
`terminal` toolset, which would let the agent read the benchmark sources or curl the server,
so it is not used here. `--ignore-rules` keeps memory/skills out, so attempts are independent.

OSWorld uses a second profile, **`bench-osworld`**, whose only tools come from the `osworld`
MCP server:

```bash
hermes profile create bench-osworld --clone-from bench --clone-all --no-alias
hermes -p bench-osworld tools disable browser
hermes -p bench-osworld mcp add osworld --command "$PWD/vendor/OSWorld/.venv/bin/python" \
    --args "$PWD/bench/osworld_mcp.py"
```

## Adding another harness

Write `bench/adapters/<name>.py` with `run(prompt, workdir, out_dir, budget_s, model=None) -> dict`
(see `bench/adapters/__init__.py` for the keys), then `./bench.sh --harness <name> --suite ...`.
The harness must drive a browser to the URL in the prompt and should be limited to browser tools.
