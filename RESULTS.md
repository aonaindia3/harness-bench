# Results

Hermes Agent v0.22.2 · model `gpt-6-luna` via ChatGPT Plus (openai-codex) · built-in browser
tools only (profile `bench`) · 1 trial per task · 240 s budget per web task · 2026-10-19.

## Summary

| Suite | Tasks | Success | Mean time | Mean tool calls | Mean tokens |
|---|---|---|---|---|---|
| MiniWoB++ quick (25 of 125) | 25 | **12/25 (48%)** | 23.5 s | 6.3 | 38.5k |
| WebGames quick, guarded (25 of 50 base) | 25 | **12/25 (48%)** | 40.8 s | 10.3 | 70.6k |
| WebGames quick, first run (unguarded) | 25 | 13/25 clean (52%); 16/25 raw (64%) | 37.9 s | 10.0 | 63.8k |
| OSWorld test_small (36 of 39; 3 need Google Drive) | 16 so far | **3/16 (19%)**, run resuming | ~66 s | 16.8 | |

Reference points (different task samples and dates, so only rough): the WebGames paper
reports ~50% for its best agent (gemini-2.5-pro) and 95.7% for humans on base tasks.

Usage: the whole MiniWoB++ + WebGames pass used ~2% of one ChatGPT Plus 5-hour window.

## Findings

1. **Reward hacking on WebGames.** In the first run Hermes used `browser_console` to
   `fetch()` the app's JS bundle and search it for the password (literally
   `matchAll(/Secret Password/)`) in 6/25 attempts; 3 of those "passed". The local server now
   serves the bundle only to real `<script>` loads, and the report counts any attempt that
   touched page internals as a failure. In the guarded run Hermes still *tried* in 4/25
   attempts (all blocked, all failed).
2. **Heavy JavaScript use instead of UI input on WebGames.** `browser_console` appeared in
   18/25 first-run attempts (92 calls) vs 0 on MiniWoB++. Many passes scripted the DOM
   (`element.click()` loops, synthetic `contextmenu` events, a Towers-of-Hanoi solver firing
   button clicks). Only 4 of the clean passes used no JavaScript at all (otp-entry,
   stock-market, text-mirror, webgl-text). WebGames' own scorer doesn't forbid this, but it
   is not "driving the UI like a person".
3. **MiniWoB++ failure modes:** date pickers (typed into the text box instead of using the
   widget, -1 reward), canvas/visual tasks (count-shape, draw-circle, moving-items,
   ascending-numbers: no element refs exposed), continuous widgets (slider, color wheel),
   and multi-step forms that never reached submit (book-flight, email-inbox-forward).
4. **OSWorld gives up early.** Of 13 failures in the first 16 tasks, 8 were Hermes calling
   `done("FAIL")` itself, usually after ~1 minute and ~16 tool calls of a 50-call budget
   (e.g. it mistyped a Calc formula into the wrong cells, quit LibreOffice to "undo", then
   declared the task impossible). 0/7 on LibreOffice Calc/Writer/Impress; passes were Chrome
   (set Bing as search engine), GIMP (reduce brightness), and killing a frozen Writer.
   Screenshots reaching the model were checked and are correct (`attempts/*/shot_*.png`).
   One failure was environmental: Google Scholar showed the VM a CAPTCHA.

## Caveats

- One trial per task; quick suites are 25-task samples. Use `--trials 3` and the `-all`
  suites before drawing fine-grained conclusions.
- Hermes's *default* browser driver (`browser_exec`, Browser Use) is not tested: Hermes only
  enables it together with the terminal toolset, which would let the agent read the
  benchmark files. These numbers are for its built-in agent-browser tools.
- MiniWoB++ episodes have no time limit here (BrowserGym also lifts the 10 s default).

Reproduce: see README. Per-task tables: `./bench.sh report runs/<run>/results.jsonl`.
