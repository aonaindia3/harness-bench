# Results

Clean run of 2026-10-20. Same model for every harness: `gpt-6-luna` at medium reasoning effort via
ChatGPT Plus. 1 trial per task, 240 s per web task; OSWorld 50 tool iterations / 900 s per task.

- **hermes**: Hermes Agent v0.22.2 with its built-in browser tools (agent-browser + headless Chromium).
- **hermes_playwright**: the same Hermes with Playwright MCP 0.0.83 instead, same Chromium build,
  limited to page-level tools (see README "Hermes with Playwright").
- **codex**: Codex CLI 0.162.0-alpha.17.2 with exactly the hermes_playwright browser tools and
  nothing else (see README "Codex setup"). Codex vs hermes_playwright differs only in the harness.

Raw rows: `results/<harness>-<model>/<suite>/results.jsonl`. Full transcripts (and for OSWorld the
agent's screenshots and a screen recording per task) are attached to the GitHub release
`results-2026-10-20`. Recompute everything below with
`./bench.sh report --compare results/*/*/results.jsonl`.

## Summary

| Suite | hermes | hermes_playwright | codex |
|---|---|---|---|
| MiniWoB++ quick (25 of 125) | **16/25 (64%)** | **15/25 (60%)** | **17/25 (68%)** |
| WebGames quick (25 of 53 base) | **12/25 (48%)** | **14/25 (56%)** | **15/25 (60%)** |
| OSWorld test_small (36 of 39; 3 need Google Drive) | **6/36 (17%)**; mean score 19.4% | n/a (no browser) | not run |

MiniWoB / WebGames per task:

| | hermes | hermes_playwright | codex |
|---|---|---|---|
| Mean time | 26.6 s / 35.7 s | 31.3 s / 34.7 s | 17.1 s / 22.1 s |
| Mean tool calls | 7.0 / 10.4 | 10.2 / 11.2 | 6.8 / 8.1 |
| Mean tokens | 45.5k / 70.3k | 57.6k / 70.3k | 110.0k / 147.0k |
| Timeouts | 0 / 0 | 0 / 0 | 0 / 0 |
| Flagged for cheating | 0 / 0 | 0 / 0 | 0 / 0 |

Tokens are input (including cached) plus output, counted the same way for both harnesses.

OSWorld: mean 81 s, 16.8 tool calls and 195k tokens per task; 0 timeouts. "Success" is a full score
(1.0); OSWorld's own metric is the mean score, which also counts one 0.99 partial (vlc).

Reference: the WebGames paper reports ~50% for its best agent and 95.7% for humans on base tasks
(different task sample and date).

## Findings

1. **Codex scores highest, but within noise.** 32/50 web tasks vs 29/50 (hermes_playwright, same
   tools) and 28/50 (hermes). It is also the fastest (about 40% less time per task) and uses the
   fewest tool calls, but about 2x the tokens (likely a larger fixed prompt per model call).
   Codex alone passed count-shape (read from a screenshot), slider-symphony and wolf-goat-cabbage
   (17 plain clicks). It failed use-slider and buttons, which hermes passed, and
   book-flight-nodelay, ladybird and verify-challenge, which hermes_playwright passed.
2. **No measurable difference between Hermes's two browser setups at this sample size.** The totals
   differ by 1 to 2 tasks per suite, within what one trial on 25 tasks can resolve. They disagree
   on 14 of 50 tasks: Playwright alone passed book-flight-nodelay, email-inbox-forward, key-combo,
   ladybird, menu-navigator and verify-challenge; the built-in tools alone passed
   click-checkboxes-soft, click-tab-2, use-slider, buttons and date.
3. **Hermes's MCP circuit breaker costs the Playwright setup.** After 3 consecutive failed calls to
   an MCP server, Hermes blocks it for 60 s (hard-coded). It fired in 3 MiniWoB attempts
   (ascending-numbers, click-checkboxes-soft, click-tab-2), all failures, typically after the model
   passed a button label where Playwright's `browser_click` expects an element ref. The built-in
   tools have no such pause, and neither does Codex.
4. **No cheating once the rule was stated.** The WebGames prompt now says page-level JavaScript is
   fine and reading the app's source or internal state is a failure; no attempt in any setup
   tried. (The earlier, superseded run had 6/25 attempts reading passwords from the JS bundle and
   others reading React internals.) All passes were also reviewed by hand: JavaScript was used for
   dispatching pointer events, scrolling and reading visible text, which the rule allows.
5. **Text snapshots make some tasks free.** context-breaker hides the password at the bottom of a
   huge text box; all three read it from the page snapshot in one step. A screenshot-based agent
   would have to scroll.
6. **Download tasks are unwinnable in every setup.** combination-lock and resume-challenge hand the
   agent a file; no setup can open a downloaded file, so all failed.
7. **OSWorld: Hermes gives up rather than runs out of budget.** Of 30 failures, 15 were Hermes
   calling `done("FAIL")` itself (median 12 tool calls of a 50-call budget, no timeouts). By app:
   LibreOffice Calc 2/3, Thunderbird 1/2, VS Code 1/3, Chrome 1/4, multi-app 1/14, and 0 on GIMP,
   Impress, Writer, OS and VLC. None of the 36 tasks is an "infeasible" task, so no `FAIL` was right.
8. **OSWorld varies a lot between runs.** Against the earlier (superseded but same-setup) run, 6
   of the 34 shared tasks flipped: 4 passes became fails and 2 fails became passes, at similar totals
   (6 vs 8). One trial per task cannot separate harnesses on OSWorld; use 3+.
9. **Failed by all three:** canvas/visual tasks (ascending-numbers, circle-center, draw-circle,
   find-midpoint, canvas-catch), click-tab-2-medium, tic-tac-toe, emoji-remember, file-credentials,
   map-panner, robo-check, and the two download tasks.

## Protocol changes since the superseded run

- MiniWoB++ uses the 125 registered environments (it had 5 unregistered pages and missed 2 tasks).
- WebGames samples from all 53 base tasks (15 lacked a `variant` field and were dropped before), so
  both quick samples differ from the earlier run's.
- Cheat check also flags React internals and local files other than the browser's own downloads.

## Caveats

- One trial per task on 25-task samples: treat differences of a few tasks as noise. Use
  `--trials 3` and the `-all` suites before drawing conclusions.
- Hermes web runs overlapped with the OSWorld run on the same ChatGPT Plus account; the Codex runs
  ran alone.
- Codex's code-mode calls (`functions.exec`) are not in its event log, only the MCP calls made from
  them, which is what the cheat check needs; its sandbox was tested to have no file, network or
  process access.
- A few OSWorld tasks use the live web (e.g. Google Scholar, travel sites), so site changes or
  CAPTCHAs can fail a task regardless of the agent.
- Hermes's default Browser Use driver (`browser_exec`) is not tested; it is only offered together
  with the terminal toolset, which would expose the benchmark files.
