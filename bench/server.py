"""Local HTTP servers for the benchmark suites.

MiniWoB++  : serves miniwob/html with a shim injected into each task page. The shim
             seeds the RNG, removes the 10 s episode limit, auto-starts the episode and
             POSTs the reward to /__bench/result (first episode only).
WebGames   : serves the built single-page app (vendor/webgames/webgames/dist) with an
             index.html fallback so deep links like /buttons work.
"""

from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHIM_PATH = HERE / "miniwob_shim.js"
SHIM_TAG = b'<script src="/__bench/miniwob_shim.js"></script>'


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class MiniWobHandler(_Quiet):
    results_dir: Path

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/__bench/miniwob_shim.js":
            return self._send(200, SHIM_PATH.read_bytes(), "application/javascript")
        if path.startswith("/miniwob/") and path.endswith(".html"):
            file = Path(self.directory) / path.lstrip("/")
            if not file.is_file():
                return self._send(404, b"not found", "text/plain")
            html = file.read_bytes()
            html = html.replace(b"</body>", SHIM_TAG + b"\n</body>", 1) if b"</body>" in html else html + SHIM_TAG
            return self._send(200, html, "text/html; charset=utf-8")
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/__bench/result":
            return self._send(404, b"not found", "text/plain")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            run = "".join(c for c in str(body.get("run", "")) if c.isalnum() or c in "-_")
        except (ValueError, TypeError):
            return self._send(400, b"bad json", "text/plain")
        if run:
            out = self.results_dir / f"{run}.json"
            if not out.exists():  # first episode wins; later episodes are ignored
                body["user_agent"] = self.headers.get("User-Agent", "")
                out.write_text(json.dumps(body))
        return self._send(204, b"", "text/plain")

    def _send(self, code, data, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)


class SpaHandler(_Quiet):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if not (Path(self.directory) / path.lstrip("/")).is_file():
            self.path = "/index.html"
        return super().do_GET()


def _serve(handler, port):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def start_miniwob(html_root: Path, results_dir: Path, port: int = 0):
    results_dir.mkdir(parents=True, exist_ok=True)
    handler = type("H", (MiniWobHandler,), {"results_dir": results_dir})
    return _serve(partial(handler, directory=str(html_root)), port)


def start_webgames(dist_root: Path, port: int = 0):
    if not (dist_root / "index.html").is_file():
        raise SystemExit(f"WebGames is not built: {dist_root}/index.html missing (run ./setup.sh)")
    return _serve(partial(SpaHandler, directory=str(dist_root)), port)
