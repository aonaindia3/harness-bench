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
python3 -m bench.watch                                # live view at http://127.0.0.1:8765
```

`python3 -m bench.replay runs/<A> runs/<B>` (http://127.0.0.1:8766) replays two OSWorld runs side by
side: both screen recordings per task with each agent's steps; click a step to seek its video.

`bench.watch` shows each active run's progress, the current task and its goal, and a live feed
of what the agent says and which tools it calls; for OSWorld it embeds the VM desktop view-only.

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
OSWorld rows also say how the attempt **ended** (`bench.report.ended`): `done` / `fail` (what the
agent declared), `steps` (step budget used up), `time` (timed out), `safety` (openai_cua stopped on
a safety check), `error` (crashed without declaring), `none` (stopped without declaring) or `env`
(OSWorld's own setup or evaluator broke). `report --compare` tallies them per harness, plus how
often the agent said done on a task the evaluator failed. API agents also record `served_model`,
the model the API reports having run.
Full transcripts are in `runs/<run>/attempts/<task>/transcript.jsonl`; OSWorld attempts also keep
the agent's screenshots, an action log and a screen recording. `runs/` is not in git; see
[Comparing harnesses](#comparing-harnesses) for sharing.

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
  Default 50 tool iterations and 900 s per task. Each task's screen is recorded to
  `attempts/<task>/recording.mp4` with OSWorld's own recorder (`--no-record` to skip).
  `--trial N` labels the rows (the report shows per-trial totals); use one `--out` per trial.
  Re-using an `--out` resumes it: finished tasks are skipped, an unfinished one starts clean.
- **Usage limits**: an attempt that ends on a plan or API usage limit (`bench/limits.py` reads the
  agent's own error output, never tool results) is not scored. The run saves the message to
  `attempts/<task>/limited.txt` and exits 75; resume it with the same `--out` once the limit
  resets. `./bench.sh osworld-queue hermes:1 openai_cua:1 ...` runs jobs back to back into
  `runs/osw-<harness>-t<trial>`, sets aside a limited harness's jobs and gives them one more pass
  at the end (arguments after `--` go to every run). For runs that must outlive the terminal or
  the session that started them, run the queue as a user service:
  `systemd-run --user --unit=osworld-queue --working-directory=$PWD ./bench.sh osworld-queue ...`
  (`systemctl --user status osworld-queue`; `nohup` and `setsid` were not enough here).
- **Replaced attempts**: an attempt lost to infrastructure (e.g. a hung API request) can be rerun
  by moving its row to `replaced-rows.jsonl` (with the reason) and its folder to
  `attempts-replaced/`, then resuming the run. Report it alongside the results.

## Test plan: Fair A case study (A5, computer-use agents)

The case study asks which parts of a computer-use agent (understanding, state, policy,
generation, knowing when it's done) are explicit, latent in the model, or missing, and where a
failure shows how it is built. The benchmark is evidence for that, so the goal is **why** a
setup scores what it does, not the highest score: one model (`gpt-6-luna`, medium effort)
throughout, only the harness changes.

Everything runs on OSWorld `test_small.json` (36 tasks) on this machine, with the limits in
[Comparing harnesses](#comparing-harnesses). The web suites, full OSWorld (369 tasks) and
OSWorld 2.0 are out of scope: OSWorld 2.0's long tasks would put every harness near 0 on this
model, so it could not separate them.

**Must run**

| # | Run | Trials | Status | What it answers |
|---|---|---|---|---|
| 1 | `hermes` (four MCP tools) vs `openai_cua` (native `computer` tool) | 3 each | trial 0 done (6/36, 23/36: `runs/clean-*-osworld-small`) | Is the harness gap (the seam) bigger than run-to-run noise? |
| 2 | `openai_fn`: the `openai_cua` loop with the same actions as a plain function tool | 3 | built, not run | Is the gap the trained action interface (latent in the model) or the loop design (copyable by any harness)? |

**Optional** (if the ChatGPT Plus limit allows)

| # | Run | Trials | Status | What it answers |
|---|---|---|---|---|
| 3 | Codex with the same four MCP tools as Hermes | 1 (3 if time) | not built (`osworld_run.py` has no Codex hook) | Is 6/36 a Hermes quirk or typical of general agent harnesses? |
| 4 | Hermes with a screenshot returned after every `execute` | 1 | not built | Does one look per action (the `openai_cua` loop) close the gap? |

Runs 1 (`openai_cua` half) and 2 bill the API key; Hermes and Codex use the ChatGPT Plus login,
whose usage limit is the bottleneck (a Hermes OSWorld task is about 195k tokens). Finish a trial
for every setup before starting the next, so a limit pause delays a whole trial rather than one
setup. About 14 h of machine time for runs 1–2, 18–22 h with 3–4. In that order:

```bash
OPENAI_API_KEY=... ./bench.sh osworld-queue hermes:1 openai_cua:1 openai_fn:0 hermes:2 openai_cua:2 openai_fn:1 openai_fn:2
./bench.sh report --compare runs/clean-*-osworld-small/results.jsonl runs/osw-*/results.jsonl
```

**Record from every run**, beyond the success rate:

- How each failed task ended: `done("DONE")` but wrong, `done("FAIL")` early, or out of steps or
  time (evidence that nothing checks whether the task is done).
- Environment failures (OSWorld setup or postconfig errors, live sites), kept apart from agent
  failures.
- Steps, time and tokens per task.
- The model each transcript reports, to confirm it is `gpt-6-luna` throughout.

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

### Hermes with Playwright (`--harness hermes_playwright`)

Same Hermes, model and prompts, but the browser is [Playwright MCP](https://github.com/microsoft/playwright-mcp)
(pinned in `setup.sh`) instead of the built-in tools, so the two runs isolate the effect of the
browser toolset. Profile **`bench-playwright`**: the built-in `browser` toolset is off and the
`playwright` MCP server runs the same Chromium build Hermes uses, headless, with an in-memory profile.

```bash
./setup.sh playwright
hermes profile create bench-playwright --clone-from bench --clone-all --no-alias
hermes -p bench-playwright tools disable browser
```

`hermes mcp add` asks interactively which tools to enable, so add the server to
`~/.hermes/profiles/bench-playwright/config.yaml` directly (adjust the two paths):

```yaml
mcp_servers:
  playwright:
    command: node
    args: [/path/to/harness-bench/vendor/playwright-mcp/node_modules/@playwright/mcp/cli.js,
           --headless, --isolated, --executable-path, ~/.hermes/tools/chromium-1208/chrome-linux64/chrome,
           --output-dir, /tmp/hb-playwright-out]
    enabled: true
    tools:
      include: [browser_navigate, browser_navigate_back, browser_snapshot, browser_take_screenshot,
                browser_find, browser_click, browser_hover, browser_drag, browser_type, browser_fill_form,
                browser_press_key, browser_select_option, browser_wait_for, browser_evaluate,
                browser_console_messages, browser_handle_dialog, browser_tabs, browser_resize,
                browser_emulate_media, browser_close]
```

The allow-list leaves out `browser_run_code_unsafe` (runs code in the server process, so it can
read local files), `browser_network_request(s)` (return response bodies, including the WebGames
bundle with every password) and `browser_file_upload` / `browser_drop`. Check with
`hermes -p bench-playwright mcp list` (should say "20 selected").

Hermes pauses an MCP server for 60 s after 3 consecutive failed calls (hard-coded circuit breaker
in `tools/mcp_tool.py`); the built-in browser tools have no such pause. That is part of what this
configuration measures, so it is left as is.

## Codex setup (`--harness codex`)

`bench/adapters/codex.py` runs `codex exec --json` with the same model and reasoning effort as the
Hermes runs (`gpt-6-luna`, medium) and the same Playwright MCP allow-list as `hermes_playwright`,
so Codex vs `hermes_playwright` differs only in the harness. Needs `./setup.sh playwright` and a
Codex CLI logged in with ChatGPT (`codex login`); the VS Code extension's bundled binary is found
automatically, or set `CODEX_BIN`.

Settings are in [`bench/codex/config.toml`](bench/codex/config.toml); the adapter writes them to an
isolated `CODEX_HOME` (`~/.codex-bench`, override with `CODEX_BENCH_HOME`) so your own Codex config,
memories, skills and plugins are not used. Only `auth.json` is shared, as a symlink, so token
refreshes keep both logged in. Each attempt runs `--ephemeral`, read-only sandbox, in an empty
temp dir.

Shell, `view_image`, web search, Codex's built-in browsers, plugins, apps and multi-agent are off.
Code mode (`functions.exec`) must stay on: this Codex version calls every tool, including MCP
tools, through it. It is a JavaScript sandbox without file, network or process access (tested:
`node:fs`, `fetch`, `child_process` all fail, and a planted canary file could not be read). Its
calls do not appear in the `--json` event log; the MCP calls made from it do, and those are what
the cheat check reads. `default_tools_approval_mode = "approve"` is required because `exec` never
prompts.

## OpenAI computer-use agent (`--harness openai_cua`)

The technology behind Operator / ChatGPT agent mode, run locally: [`bench/cua/agent.mjs`](bench/cua/agent.mjs)
loops the Responses API [`computer` tool](https://developers.openai.com/api/docs/guides/tools-computer-use)
(`gpt-6-luna`, medium effort) over a headless Chromium (same build as the other harnesses,
1280x720) driven by the Playwright copy from `./setup.sh playwright`. The model sees only
screenshots and answers with mouse/keyboard actions; it has no DOM, no JavaScript and no address
bar, so the page from the prompt is opened before the first screenshot. Pending safety checks stop
the attempt (there is no one to approve them).

Needs an API key with pay-per-token billing (ChatGPT plans don't cover it):
`OPENAI_API_KEY=... ./bench.sh --harness openai_cua --suite miniwob-quick`. Measured on gpt-6-luna:
about $0.0005 per MiniWoB task and $0.01 per WebGames task (most input is cached screenshots).
`OPENAI_CUA_MODEL` / `OPENAI_CUA_EFFORT` change the model and effort. Each attempt keeps its
screenshots (`attempts/<task>/shot_*.png`) next to the transcript.

For OSWorld: `OPENAI_API_KEY=... ./bench.sh osworld --harness openai_cua` ([`bench/cua/osworld_agent.py`](bench/cua/osworld_agent.py)).
Screenshots are full 1920x1080; actions run as pyautogui code through OSWorld's controller, the same
path Hermes's `execute` tool uses. A final message starting with FAIL becomes OSWorld's FAIL action.

`--harness openai_fn` is the same agent with one change: the actions come through an ordinary
function tool named `computer` (same action objects, batched the same way, a full-resolution
screenshot returned after each call) instead of the native computer tool. Comparing the two
separates what the trained action interface contributes from what the loop design does. The
function version has no safety checks, since those come with the native tool.

## Adding another harness

Write `bench/adapters/<name>.py` with `run(prompt, workdir, out_dir, budget_s, model=None) -> dict`
(see `bench/adapters/__init__.py` for the keys), then `./bench.sh --harness <name> --suite ...`.
The harness must drive a browser to the URL in the prompt and should be limited to browser tools.
Return `tool_inputs` (every tool call's input as a string): the cheat check reads them, and a
harness that leaves them out is never flagged. Return `model` and expose `version()` if you can;
both end up in the results so the comparison table can tell runs apart.

For OSWorld, add an entry to `HARNESSES` in `bench/osworld_run.py`: a `run(ex, attempt, env, args)`
that drives the VM for one task (see `run_hermes`), a `version()` and a transcript parser (see the
`Harness` docstring). Keep the rest the same: the prompt, the four tools from
`bench/osworld_mcp.py`, the 50-step and 900 s limits, OSWorld's evaluator. If the harness's usage
limit errors aren't caught by `bench/limits.py`, add their wording to its `PATTERN`.

Tests (no VM or extra packages needed): `python3 -m unittest discover tests`.

## Comparing harnesses

Keep everything below the same so the numbers line up; change only the harness (and say so if
you change the model).

| | Setting |
|---|---|
| Tasks | `miniwob-quick`, `webgames-quick` (fixed seed, same 25 for everyone), OSWorld `test_small.json` (36; 3 Google Drive tasks skipped) |
| Trials | 1 per task (use `--trials 3` for tighter numbers, and report it; OSWorld: one run per trial with `--trial N`) |
| Limits | web: 240 s per attempt; OSWorld: 50 tool iterations, 900 s |
| Tools | web: browser tools only, no terminal/file/web-search tools (Hermes: built-in browser or the Playwright allow-list above); OSWorld: only the four MCP tools |
| Isolation | fresh session per attempt, no memory, skills or rules carried between attempts |
| Prompts | as in `bench/tasks.py` and `bench/osworld_run.py`, unchanged |
| Cheating | JavaScript on the page's elements is allowed; reading the app's source or internal state is a failure (`suspect`) |

Record the harness version, model, and how it was billed (plan or API) with the results.

Share a finished run:

```bash
./bench.sh publish runs/<run>                 # -> results/<harness>-<model>/<suite>/ + dist/*.tar.gz
git add results/ && git commit -m "results: <harness> <suite>" && git push
gh release upload <tag> dist/<harness>-<model>-<suite>.tar.gz   # transcripts, screenshots, videos
./bench.sh report --compare results/*/*/results.jsonl          # all harnesses side by side
```
