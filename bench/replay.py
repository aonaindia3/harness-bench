"""Side-by-side replay of two OSWorld runs: both screen recordings plus each agent's steps.

    python3 -m bench.replay runs/<run A> runs/<run B> [--port 8766]
    then open http://127.0.0.1:8766

The index lists every task with both outcomes (filter to tasks where the runs disagree). A task
page plays the two recordings next to each other and lists each agent's steps; clicking a step
seeks its video there (recording.status.json gives the recording's start time). Read-only.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from bench.report import passed
from bench.watch import _events

STYLE = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#e3e3de;--pass:#1f7a3d;--fail:#b3261e;--do:#2b5fb3;--code:#f0f0ec}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1d;--ink:#ecece8;--mute:#9a9a94;--line:#33332f;--pass:#5cc27e;--fail:#f08a80;--do:#86aef0;--code:#2a2a27}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,sans-serif}
header{padding:12px 16px;border-bottom:1px solid var(--line)}header h1{font-size:16px;margin:0}a{color:var(--do)}
main{padding:16px}.meta{color:var(--mute);font-size:12px}.p{color:var(--pass);font-weight:600}.f{color:var(--fail);font-weight:600}
table{border-collapse:collapse;width:100%;background:var(--card)}td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{font-size:12px;color:var(--mute)}tr.hide{display:none}
.goal{padding:10px 12px;background:var(--code);border-radius:6px;margin-bottom:12px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media (max-width:1000px){.cols{grid-template-columns:1fr}}
.col{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;min-width:0}
video{width:100%;border-radius:6px;background:#000}.steps{max-height:55vh;overflow:auto;margin-top:8px}
.ev{padding:4px 0;border-bottom:1px dashed var(--line);white-space:pre-wrap;word-break:break-word;cursor:pointer}
.ev:hover{background:var(--code)}.ev b{font-size:11px;text-transform:uppercase;margin-right:6px}.t{color:var(--mute);font-size:11px;margin-right:6px}
.say b{color:var(--mute)}.do b{color:var(--do)}.error b,.error{color:var(--fail)}.final b{color:var(--pass)}
code{background:var(--code);padding:1px 4px;border-radius:4px;font-size:12px}
"""


def _rows(run: Path) -> dict[str, dict]:
    return {r["task"]: r for r in map(json.loads, (run / "results.jsonl").read_text().splitlines()) if r}


def _attempt(run: Path, task: str) -> Path:
    return run / "attempts" / task.replace("/", "__", 1)


def web_video(attempt: Path) -> Path | None:
    """OSWorld's recorder writes H.264 High 4:4:4 (yuv444p), which browsers can't decode. Convert
    once to yuv420p next to the original (recording.web.mp4) and serve that."""
    src, dst = attempt / "recording.mp4", attempt / "recording.web.mp4"
    if not src.exists():
        return None
    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        tmp = dst.with_suffix(".tmp.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-c:v", "libx264", "-preset", "veryfast",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(tmp)], check=True)
        tmp.replace(dst)
    return dst


def _steps(attempt: Path) -> list[dict]:
    """Events with their offset into the recording, in seconds (None when unknown)."""
    events, _ = _events(attempt / "transcript.jsonl", limit=None)
    try:
        start = json.loads((attempt / "recording.status.json").read_text())["recording"]["started_at"]
    except (OSError, KeyError, ValueError):
        start = None
    for e in events:
        e["at"] = round(e["t"] / 1000 - start, 1) if (start and e.get("t")) else None
    return events


def _badge(r: dict | None) -> str:
    if r is None:
        return '<span class="meta">-</span>'
    return f'<span class="{"p" if passed(r) else "f"}">{"PASS" if passed(r) else "fail"}</span>'


def index_page(runs: list[Path]) -> str:
    rows = [_rows(r) for r in runs]
    tasks = sorted(set().union(*rows))
    body = []
    for t in tasks:
        res = [rs.get(t) for rs in rows]
        differ = len({bool(r and passed(r)) for r in res}) > 1
        instr = html.escape((res[0] or res[1] or {}).get("instruction", "")[:140])
        cells = "".join(f"<td>{_badge(r)}<div class='meta'>{(r or {}).get('detail') or ''}</div></td>" for r in res)
        body.append(f'<tr data-differ="{int(differ)}"><td><a href="/task?t={t}">{html.escape(t.split("/")[0])}/'
                    f'{html.escape(t.split("/")[1][:8])}</a></td><td>{instr}</td>{cells}</tr>')
    totals = " · ".join(f"{r.name}: {sum(passed(x) for x in rs.values())}/{len(rs)}" for r, rs in zip(runs, rows))
    heads = "".join(f"<th>{html.escape(r.name)}</th>" for r in runs)
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OSWorld Replay</title><style>{STYLE}</style></head><body>
<header><h1>OSWorld replay</h1><div class="meta">{totals}</div></header><main>
<label><input type="checkbox" id="differ"> only tasks where the runs disagree</label>
<table><tr><th>task</th><th>instruction</th>{heads}</tr>{''.join(body)}</table></main>
<script>document.getElementById('differ').onchange=e=>document.querySelectorAll('tr[data-differ]').forEach(r=>r.classList.toggle('hide',e.target.checked&&r.dataset.differ==='0'))</script>
</body></html>"""


def task_page(runs: list[Path], task: str) -> str:
    cols = []
    instruction = ""
    for i, run in enumerate(runs):
        r = _rows(run).get(task)
        a = _attempt(run, task)
        instruction = instruction or (r or {}).get("instruction", "")
        video = (f'<video id="v{i}" controls muted src="/file?run={i}&t={task}&f=recording.mp4"></video>'
                 if (a / "recording.mp4").exists() else '<div class="meta">no recording</div>')
        steps = []
        for e in _steps(a):
            label = {"say": "says", "do": "does", "error": "error", "final": "answer"}[e["kind"]]
            body = f'{html.escape(e["tool"])} <code>{html.escape(e["text"][:600])}</code>' if e["kind"] == "do" else html.escape(e["text"][:1500])
            at = f'<span class="t">{e["at"]:.0f}s</span>' if e["at"] is not None else ""
            steps.append(f'<div class="ev {e["kind"]}" data-v="v{i}" data-at="{e["at"] if e["at"] is not None else ""}">{at}<b>{label}</b>{body}</div>')
        info = "" if r is None else f'{_badge(r)} <span class="meta">score {r["score"]:.2f} · {r["wall_s"]}s · {r["tool_calls"]} tool calls · {html.escape(r.get("detail") or "")}</span>'
        cols.append(f'<div class="col"><h2 style="font-size:14px;margin:0 0 6px">{html.escape(run.name)}</h2>{info}{video}'
                    f'<div class="steps">{"".join(steps) or "<div class=meta>no steps</div>"}</div></div>')
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OSWorld Replay</title><style>{STYLE}</style></head><body>
<header><h1><a href="/">OSWorld replay</a> / {html.escape(task)}</h1></header><main>
<div class="goal">{html.escape(instruction)}</div>
<div class="meta" style="margin-bottom:8px">Videos play at 2x. Click a step to jump its video there.
<button id="both">play both</button></div><div class="cols">{''.join(cols)}</div></main>
<script>
const vids=[...document.querySelectorAll('video')];vids.forEach(v=>{{v.playbackRate=2;v.addEventListener('loadedmetadata',()=>v.playbackRate=2)}});
document.getElementById('both').onclick=()=>vids.forEach(v=>{{v.currentTime=0;v.play()}});
document.querySelectorAll('.ev[data-at]').forEach(el=>el.onclick=()=>{{const v=document.getElementById(el.dataset.v);if(v&&el.dataset.at!==''){{v.currentTime=Math.max(0,+el.dataset.at);v.play()}}}});
</script></body></html>"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs=2, help="two OSWorld run directories (runs/<run>)")
    ap.add_argument("--port", type=int, default=8766)
    args = ap.parse_args(argv)
    runs = [Path(r).resolve() for r in args.runs]
    print("converting recordings for the browser (first start only)...", flush=True)
    for run in runs:
        for a in sorted((run / "attempts").glob("*")):
            web_video(a)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body: bytes, ctype, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/":
                return self._send(200, index_page(runs).encode(), "text/html; charset=utf-8")
            if u.path == "/task" and "t" in q:
                return self._send(200, task_page(runs, unquote(q["t"])).encode(), "text/html; charset=utf-8")
            if u.path == "/file" and q.get("f") == "recording.mp4" and q.get("run") in ("0", "1"):
                f = _attempt(runs[int(q["run"])], unquote(q.get("t", ""))).resolve()
                if runs[int(q["run"])] not in f.parents or not (f / "recording.mp4").is_file():
                    return self._send(404, b"not found", "text/plain")
                path = web_video(f)
                data = path.read_bytes()
                rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
                if rng:  # browsers need ranges to seek
                    start = int(rng.group(1) or 0)
                    end = min(int(rng.group(2) or len(data) - 1), len(data) - 1)
                    return self._send(206, data[start:end + 1], "video/mp4",
                                      {"Content-Range": f"bytes {start}-{end}/{len(data)}", "Accept-Ranges": "bytes"})
                return self._send(200, data, "video/mp4", {"Accept-Ranges": "bytes"})
            return self._send(404, b"not found", "text/plain")

    print(f"replay: http://127.0.0.1:{args.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
