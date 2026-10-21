"""Live view of benchmark runs: current task, its goal, and what the agent is saying/doing.

    python3 -m bench.watch                       # runs active in the last 30 min
    python3 -m bench.watch runs/<run> [...]      # specific runs
    then open http://127.0.0.1:8765

Read-only: it only reads runs/<run>/ (config, results.jsonl, attempts/*/transcript.jsonl).
For OSWorld the page also embeds the VM's noVNC viewer (port 8006) in view-only mode.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bench.report import passed
from bench.tasks import ROOT, webgames_tasks

OSW_EXAMPLES = ROOT / "vendor" / "OSWorld" / "evaluation_examples" / "examples"
VNC_PORT = 8006
VNC_URL = f"http://localhost:{VNC_PORT}/?resize=scale&reconnect=true&autoconnect=true&view_only=true"
ACTIVE_S = 30 * 60
MAX_EVENTS = 80


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _mtime(run: Path) -> float:
    paths = [run, run / "results.jsonl", *(run / "attempts").glob("*")]
    paths += [p / "transcript.jsonl" for p in paths[2:]]
    return max((p.stat().st_mtime for p in paths if p.exists()), default=0)


def _goal(suite: str, task: str) -> str:
    if suite == "osworld":
        dom, tid = task.split("/", 1)
        f = OSW_EXAMPLES / dom / f"{tid}.json"
        return json.loads(f.read_text())["instruction"] if f.exists() else ""
    if suite == "webgames":
        meta = next((t.meta for t in webgames_tasks() if t.id == task), {})
        return f"{meta.get('title', task)}: {meta.get('description', '')}"
    return "The task instruction is shown at the top of the MiniWoB++ page (the agent reads it there)."


def _brief(name: str, inp) -> str:
    if isinstance(inp, dict):
        if "code" in inp:
            return inp["code"]
        if "expression" in inp:
            return inp["expression"]
        inp = {k: v for k, v in inp.items() if v not in (None, "", [], {})}
    s = json.dumps(inp, ensure_ascii=False)
    return s[:400] + ("…" if len(s) > 400 else "")


def _events(transcript: Path) -> tuple[list[dict], bool]:
    events: list[dict] = []
    finished = False
    if not transcript.exists():
        return events, finished
    for line in transcript.read_text(errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        kind, ts = ev.get("type"), ev.get("timestamp")
        if kind == "text":
            if events and events[-1]["kind"] == "say":
                events[-1]["text"] += ev.get("text", "")
            else:
                events.append({"kind": "say", "text": ev.get("text", ""), "t": ts})
        elif kind == "tool_use":
            name = re.sub(r"^mcp_+[a-z0-9-]+_+", "", ev.get("name", "?"))
            events.append({"kind": "do", "tool": name, "text": _brief(name, ev.get("input")), "t": ts})
        elif kind == "tool_result" and ev.get("is_error"):
            events.append({"kind": "error", "text": str(ev.get("output", ""))[:300], "t": ts})
        elif kind == "result":
            finished = True
            events.append({"kind": "final", "text": ev.get("text", ""), "t": ts})
        # Codex `exec --json` events (bench/adapters/codex.py)
        elif kind in ("item.started", "item.completed"):
            item = ev.get("item") or {}
            if item.get("type") == "mcp_tool_call" and kind == "item.started":
                events.append({"kind": "do", "tool": item.get("tool", "?"),
                               "text": _brief(item.get("tool"), item.get("arguments")), "t": None})
            elif item.get("type") == "mcp_tool_call" and item.get("error"):
                events.append({"kind": "error", "text": str(item["error"].get("message", ""))[:300], "t": None})
            elif item.get("type") == "agent_message" and kind == "item.completed":
                events.append({"kind": "say", "text": item.get("text", ""), "t": None})
            elif item.get("type") == "error":
                events.append({"kind": "error", "text": item.get("message", "")[:300], "t": None})
        elif kind == "turn.completed":
            finished = True
            if events and events[-1]["kind"] == "say":
                events[-1]["kind"] = "final"
    for e in events:
        e["text"] = e["text"].strip()
    return [e for e in events if e["text"]][-MAX_EVENTS:], finished


def run_state(run: Path) -> dict:
    cfg = json.loads((run / "config.json").read_text()) if (run / "config.json").exists() else {}
    rows = _rows(run / "results.jsonl")
    suite = cfg.get("suite") or ("osworld" if "tasks_file" in cfg else "?")
    total = (cfg.get("n_tasks") or 0) * (cfg.get("trials") or 1)
    if suite == "osworld":  # a resumed run's n_tasks only counts what was left
        total = max(total, len(rows))
    attempts = sorted((run / "attempts").glob("*"), key=lambda p: p.stat().st_mtime) if (run / "attempts").exists() else []
    current = None
    if attempts:
        a = attempts[-1]
        parts = a.name.split("__")
        if parts[0] in ("miniwob", "webgames"):
            task_suite, task = parts[0], parts[1]
            done = any(r["task"] == task and f"t{r['trial']}" == parts[2] for r in rows)
        else:
            task_suite, task = "osworld", f"{parts[0]}/{parts[1]}"
            done = any(r["task"] == task for r in rows)
        events, finished = _events(a / "transcript.jsonl")
        if done:
            status = "finished"
        elif finished:
            status = "agent finished; scoring"
        elif not (a / "transcript.jsonl").exists():
            status = "setting up the task" if task_suite == "osworld" else "starting"
        else:
            status = "agent working"
        row = next((r for r in reversed(rows) if r["task"] == task), None) if done else None
        current = {"task": task, "suite": task_suite, "goal": _goal(task_suite, task), "status": status,
                   "started": a.stat().st_ctime, "events": events,
                   "result": None if row is None else ("PASS" if passed(row) else "fail")}
    return {"run": run.name, "suite": suite, "done": len(rows), "total": total,
            "passes": sum(passed(r) for r in rows), "updated": _mtime(run),
            "recent": [{"task": r["task"], "pass": passed(r), "suspect": bool(r.get("suspect"))} for r in rows[-8:]][::-1],
            "current": current}


def vnc_up() -> bool:
    # OSWorld's docker provider recreates the VM container for every task, so the viewer is
    # unreachable for a while between tasks; the page waits for it instead of showing an error.
    # Docker's port proxy accepts connections before noVNC inside is up, so ask for the page itself.
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{VNC_PORT}/vnc.html", timeout=0.5) as r:
            return r.status == 200
    except (OSError, ValueError):
        return False


def pick_runs(explicit: list[str]) -> list[Path]:
    if explicit:
        return [Path(p).resolve() for p in explicit]
    runs = [p for p in (ROOT / "runs").iterdir() if p.is_dir() and not p.name.startswith(".")]
    runs.sort(key=_mtime, reverse=True)
    active = [p for p in runs if time.time() - _mtime(p) < ACTIVE_S]
    return active or runs[:1]


PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Benchmark Watch</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#e3e3de;--pass:#1f7a3d;--fail:#b3261e;--do:#2b5fb3;--say:#1d1d1b;--code:#f0f0ec}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1d;--ink:#ecece8;--mute:#9a9a94;--line:#33332f;--pass:#5cc27e;--fail:#f08a80;--do:#86aef0;--say:#ecece8;--code:#2a2a27}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,sans-serif}
header{padding:12px 16px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:baseline;flex-wrap:wrap}
header h1{font-size:16px;margin:0}header span{color:var(--mute);font-size:12px}
main{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);gap:16px;padding:16px}
@media (max-width:1000px){main{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-bottom:16px}
.vnc{aspect-ratio:16/9;width:100%;border:0;border-radius:6px;background:#000;display:block}
.vncwait{aspect-ratio:16/9;width:100%;border-radius:6px;background:#000;color:#bbb;display:flex;align-items:center;justify-content:center;text-align:center;padding:16px}
h2{font-size:14px;margin:0 0 6px}.meta{color:var(--mute);font-size:12px}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden;margin:6px 0 10px}.bar i{display:block;height:100%;background:var(--do)}
.task{font-weight:600}.goal{margin:4px 0 8px;padding:8px 10px;background:var(--code);border-radius:6px}
.status{display:inline-block;font-size:12px;padding:1px 8px;border-radius:10px;border:1px solid var(--line);color:var(--mute)}
.feed{max-height:52vh;overflow:auto;border-top:1px solid var(--line);margin-top:8px;padding-top:6px}
.ev{padding:4px 0;border-bottom:1px dashed var(--line);white-space:pre-wrap;word-break:break-word}
.ev b{font-size:11px;text-transform:uppercase;letter-spacing:.04em;margin-right:6px}
.say b{color:var(--mute)}.do b{color:var(--do)}.do code{background:var(--code);padding:1px 4px;border-radius:4px;font-size:12px}
.error b,.error{color:var(--fail)}.final b{color:var(--pass)}
.recent{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}.recent span{font-size:11px;padding:1px 6px;border-radius:4px;border:1px solid var(--line)}
.p{color:var(--pass)}.f{color:var(--fail)}
</style></head><body>
<header><h1>Benchmark watch</h1><span id="clock"></span><span>Read-only. The desktop view ignores your mouse and keyboard.</span></header>
<main><section id="left"></section><section id="right"></section></main>
<script>
const VNC = __VNC__;
let vncShown = false, vncLive = null, vncTask = null;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const ago = t => { const s = Math.max(0, Math.round(Date.now()/1000 - t)); return s < 60 ? s + " s" : Math.floor(s/60) + " min " + (s%60) + " s"; };
function card(r) {
  const c = r.current, pct = r.total ? 100 * r.done / r.total : 0;
  let h = `<div class="card" data-run="${esc(r.run)}"><h2>${esc(r.suite)} <span class="meta">${esc(r.run)}</span></h2>
    <div class="meta">${r.done}/${r.total || "?"} done · ${r.passes} passed</div><div class="bar"><i style="width:${pct}%"></i></div>`;
  if (c) {
    h += `<div><span class="task">${esc(c.task)}</span> <span class="status">${esc(c.status)}${c.result ? " · " + c.result : ""}</span>
      <span class="meta">· ${ago(c.started)}</span></div><div class="goal">${esc(c.goal)}</div><div class="feed">`;
    for (const e of c.events) {
      const label = {say: "says", do: "does", error: "error", final: "answer"}[e.kind];
      const body = e.kind === "do" ? `${esc(e.tool)} <code>${esc(e.text)}</code>` : esc(e.text);
      h += `<div class="ev ${e.kind}"><b>${label}</b>${body}</div>`;
    }
    if (!c.events.length) h += `<div class="meta">nothing yet</div>`;
    h += `</div>`;
  }
  if (r.recent.length) h += `<div class="recent">` + r.recent.map(x => `<span class="${x.pass ? "p" : "f"}">${x.pass ? "PASS" : "fail"} ${esc(x.task.split("/").pop().slice(0, 28))}${x.suspect ? " (suspect)" : ""}</span>`).join("") + `</div>`;
  return h + `</div>`;
}
async function tick() {
  document.getElementById("clock").textContent = new Date().toLocaleTimeString();
  let s; try { s = await (await fetch("/state")).json(); } catch { return; }
  const osw = s.runs.filter(r => r.suite === "osworld"), web = s.runs.filter(r => r.suite !== "osworld");
  const left = document.getElementById("left"), right = document.getElementById("right");
  if (osw.length && !vncShown) { left.insertAdjacentHTML("afterbegin", `<div class="card"><h2>OSWorld desktop (live, view-only)</h2><div id="vnc"></div></div><div id="oswcards"></div>`); vncShown = true; }
  if (vncShown) {
    // Reload the viewer whenever the VM comes back or a new task starts (each task gets a fresh VM).
    const task = osw[0]?.current?.task ?? null, box = document.getElementById("vnc");
    if (!s.vnc && vncLive !== false) box.innerHTML = `<div class="vncwait">The desktop is restarting for the next task. The view will come back on its own.</div>`;
    else if (s.vnc && (vncLive !== true || task !== vncTask)) box.innerHTML = `<iframe class="vnc" src="${VNC}"></iframe>`;
    vncLive = s.vnc; vncTask = task;
  }
  const scrolls = {};
  document.querySelectorAll(".card[data-run]").forEach(el => { const f = el.querySelector(".feed"); if (f) scrolls[el.dataset.run] = f.scrollHeight - f.scrollTop - f.clientHeight < 40 ? null : f.scrollTop; });
  (vncShown ? document.getElementById("oswcards") : left).innerHTML = osw.map(card).join("");
  right.innerHTML = web.map(card).join("") || (osw.length ? "" : `<div class="card meta">No active runs.</div>`);
  document.querySelectorAll(".card[data-run]").forEach(el => { const f = el.querySelector(".feed"); if (!f) return; const v = scrolls[el.dataset.run]; f.scrollTop = v == null ? f.scrollHeight : v; });
}
tick(); setInterval(tick, 1500);
</script></body></html>"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="*", help="run directories (default: runs active in the last 30 min)")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)
    page = PAGE.replace("__VNC__", json.dumps(VNC_URL)).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/state"):
                runs = pick_runs(args.runs)
                body = json.dumps({"runs": [run_state(r) for r in runs], "vnc": vnc_up()}).encode()
                ctype = "application/json"
            elif self.path in ("/", "/index.html"):
                body, ctype = page, "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"watching: http://127.0.0.1:{args.port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
