# Results

Team runs of 2026-10-20/21. Same model for every harness: `gpt-6-luna`. 1 trial per task, 240 s per
web task, the same 25 MiniWoB++ and 25 WebGames tasks (`*-quick`); OSWorld 50 tool iterations /
900 s per task.

| Harness | Run by | Browser | Results folder |
|---|---|---|---|
| **hermes**: Hermes Agent v0.22.2 | Ander | built-in (agent-browser + headless Chromium) | `hermes-gpt-6-luna` |
| **hermes_playwright**: same Hermes | Ander | Playwright MCP 0.0.83, page-level tools only (README "Hermes with Playwright") | `hermes_playwright-gpt-6-luna` |
| **codex**: Codex CLI 0.163.0 | Anusha (macOS) | Playwright MCP | `codex-gpt-6-luna-mac` |
| **codex (replication)**: Codex CLI 0.162.0-alpha.17.2, `bench/adapters/codex.py` | Ander (Linux) | Playwright MCP, the hermes_playwright allow-list | `codex-gpt-6-luna-replication` |
| **opencode**: OpenCode 1.19.3 | Clara | Playwright MCP | `opencode-openai-gpt-6-luna` |
| **openai_cua**: OpenAI computer tool (Operator's technology), `bench/cua/` | Ander | screenshots only, mouse/keyboard actions on a local Chromium (README "OpenAI computer-use agent") | `openai_cua-gpt-6-luna` |

Hermes runs used medium reasoning effort via ChatGPT Plus; openai_cua used medium effort via the
API (pay per token: $0.11 for both web suites, $0.21 for OSWorld). The Codex and OpenCode adapters and
their settings (login type, reasoning effort, exact tool list) are not in the repo yet; see
"Reproducibility" below. Recompute the tables with
`./bench.sh report --compare results/*/*-quick/results.jsonl`.

## Summary

| Suite | hermes | hermes_playwright | codex | codex (replication) | opencode | openai_cua |
|---|---|---|---|---|---|---|
| MiniWoB++ quick (25 of 125) | 16/25 (64%) | 15/25 (60%) | 19/25 (76%) | 17/25 (68%) | **20/25 (80%)** | **20/25 (80%)** |
| WebGames quick (25 of 53 base) | 12/25 (48%) | 14/25 (56%) | 15/25 (60%) | 15/25 (60%) | 16/25 (64%) | **20/25 (80%)** |
| OSWorld test_small (36 of 39) | **6/36 (17%)**; mean score 19.4% | n/a (no browser) | not valid (see below) | not run | not run | **23/36 (64%)**; mean score 69.4% |

MiniWoB / WebGames per task:

| | hermes | hermes_playwright | codex | codex (replication) | opencode | openai_cua |
|---|---|---|---|---|---|---|
| Mean time | 26.6 s / 35.7 s | 31.3 s / 34.7 s | 19.8 s / 23.2 s | 17.1 s / 22.1 s | 22.5 s / 29.4 s | 9.4 s / 53.3 s |
| Mean tool calls | 7.0 / 10.4 | 10.2 / 11.2 | 7.6 / 11.6 | 6.8 / 8.1 | 8.0 / 10.9 | 4.7 / 22.0 (screen actions) |
| Mean tokens | 45.5k / 70.3k | 57.6k / 70.3k | 126.4k / 176.3k | 110.0k / 147.0k | 43.3k / 70.0k | 11.6k / 143.5k |
| Timeouts | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 1 |
| Flagged for cheating | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 1 (false positive, see 7) | 0 / 0 |

OSWorld per task: Hermes 81 s, 16.8 tool calls, 195k tokens; openai_cua 66 s, 22.8 screen actions,
245k tokens. 0 timeouts for either. "Success" is a
full score (1.0); OSWorld's own metric is the mean score, which also counts one 0.99 partial (vlc).

Reference: the WebGames paper reports ~50% for its best agent and 95.7% for humans on base tasks
(different task sample and date).

## Findings

1. **The screenshot-only agent (openai_cua) scores highest: 40/50 web tasks.** It is the only
   harness that sees the page as pixels and acts with the mouse, and it alone passed five tasks:
   canvas-catch (one drag), map-panner (three map drags), ascending-numbers, emoji-remember and
   resume-challenge. Because the jump was large, every one of its 20 WebGames passes was checked:
   the password is on the final screenshot in each (16 by OCR, 4 by eye), and it has no DOM,
   JavaScript or file access to get it any other way. It is fast on MiniWoB (9 s) but slow on
   WebGames (53 s, 22 actions per task) and cost $0.11 for all 50 tasks.
2. **On OSWorld the screenshot agent passes 23/36 against Hermes's 6/36, on the same model.** It
   passed every task Hermes passed plus 17 more, including all of LibreOffice Calc (3/3) and Impress
   (2/2), GIMP (2/2), Thunderbird (2/2) and VS Code (3/3); multi-app 6/14, VLC 0/2. Both runs use
   the same runner and OSWorld's own evaluator, which scores the final VM state, so an answer
   cannot be guessed. Spot checks of new passes match the task: strike-through applied and saved in
   Impress, `sysstat` installed and `sar -u 1 30` written to the requested file from a terminal, the
   Thunderbird account removed through its settings. Unlike Hermes it never declared a task
   impossible; one task failed in OSWorld's own post-task setup ("Postconfig setup failed").
   The gap (17 tasks) is far larger than the 6-task run-to-run swing seen for Hermes (finding 11).
3. **Two independent Codex runs agree.** Anusha's (macOS, Codex 0.163.0, her adapter) and Ander's
   (Linux, Codex 0.162.0-alpha, `bench/adapters/codex.py`) scored 34/50 and 32/50 and gave the same
   outcome on 46 of 50 tasks (they differ on circle-center, use-slider, combination-lock and
   slider-symphony). That puts run-to-run noise for a text harness at roughly 2 to 4 tasks per 50,
   so gaps of that size below should not be read as rankings.
4. **OpenCode and Codex lead Hermes on the web suites.** 36/50 (OpenCode) and 34/50 (Codex) against
   29/50 and 28/50 for the two Hermes setups, all on the same model. That gap is larger than
   anything between Hermes's own setups, but it comes from one trial per task; confirm with
   `--trials 3` before ranking. Codex used 2 to 3 times the tokens of the others; OpenCode used about
   the same as Hermes. 22 of 50 tasks were passed by every run.
5. **No measurable difference between Hermes's two browser setups.** The totals differ by 1 to 2
   tasks per suite. They disagree on 14 of 50 tasks in both directions.
6. **Hermes's MCP circuit breaker costs the Playwright setup.** After 3 consecutive failed calls to
   an MCP server, Hermes blocks it for 60 s (hard-coded). It fired in 3 MiniWoB attempts
   (ascending-numbers, click-checkboxes-soft, click-tab-2), all failures, typically after the model
   passed a button label where Playwright's `browser_click` expects an element ref. Hermes's
   built-in tools have no such pause.
7. **No cheating in any run.** The WebGames prompt says page-level JavaScript is fine and reading
   the app's source or internal state is a failure. The Hermes runs were also reviewed by hand. The
   one flag (OpenCode, file-credentials) is the agent trying to open a file the task had it
   download; the check only allows the Hermes download folder, and the attempt failed anyway.
8. **Text snapshots make some tasks free.** context-breaker hides the password at the bottom of a
   huge text box; every text-based run read it from the page snapshot in one step.
9. **Downloaded files.** combination-lock and resume-challenge hand the agent a file. The Hermes
   setups, OpenCode and the Codex replication could not open it and failed both; Anusha's Codex run
   passed combination-lock (its transcripts are not in the release, so how it read the file is not
   checked); openai_cua passed
   resume-challenge after 180 screen actions (password confirmed on its final screenshot).
10. **OSWorld: Hermes gives up rather than runs out of budget.** Of 30 failures, 15 were Hermes
   calling `done("FAIL")` itself (median 12 tool calls of a 50-call budget, no timeouts). By app:
   LibreOffice Calc 2/3, Thunderbird 1/2, VS Code 1/3, Chrome 1/4, multi-app 1/14, and 0 on GIMP,
   Impress, Writer, OS and VLC. None of the 36 tasks is an "infeasible" task, so no `FAIL` was right.
11. **OSWorld varies a lot between runs.** Against an earlier same-setup Hermes run, 6 of the 34
   shared tasks flipped (4 passes became fails, 2 fails became passes) at similar totals (6 vs 8).
   One trial per task cannot separate harnesses on OSWorld; use 3+.
12. **Failed by every run (web):** click-tab-2-medium, draw-circle, file-credentials, robo-check.

## Reproducibility

- **hermes, hermes_playwright, openai_cua**: adapters, profiles and Playwright pin are in the repo
  (README); full transcripts and screenshots (and for OSWorld screen recordings) are in release
  `results-2026-10-20`. openai_cua needs an `OPENAI_API_KEY`; on OSWorld run it with
  `./bench.sh osworld --harness openai_cua`.
- **codex (replication)**: adapter and settings in the repo (README "Codex setup"), transcripts in
  the release.
- **codex** (Anusha) and **opencode** (Clara): only `results.jsonl` and `config.json` are in the
  repo. To reproduce or audit them we still need each adapter, its setup (login type, reasoning
  effort, MCP tool allow-list) and the transcripts.
- **codex on OSWorld** (`results/codex-gpt-6-luna-mac-emulated/osworld`) is **not a valid result**:
  it ran under emulation on macOS and had infrastructure failures (5 tasks failed during setup,
  0/30 overall). OSWorld needs a Linux host with KVM.

## Protocol changes since the superseded run

- MiniWoB++ uses the 125 registered environments (it had 5 unregistered pages and missed 2 tasks).
- WebGames samples from all 53 base tasks (15 lacked a `variant` field and were dropped before), so
  both quick samples differ from the earlier run's.
- Cheat check also flags React internals and local files other than the browser's own downloads.

## Caveats

- One trial per task on 25-task samples: treat differences of a few tasks as noise. Use
  `--trials 3` and the `-all` suites before drawing conclusions.
- The harnesses ran on different machines and days; Hermes's web runs overlapped with its OSWorld
  run on the same ChatGPT Plus account.
- A few OSWorld tasks use the live web (e.g. Google Scholar, travel sites), so site changes or
  CAPTCHAs can fail a task regardless of the agent.
- Hermes's default Browser Use driver (`browser_exec`) is not tested; it is only offered together
  with the terminal toolset, which would expose the benchmark files.
