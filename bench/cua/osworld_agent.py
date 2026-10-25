"""OpenAI computer-use agent on the OSWorld VM (run inside bench/osworld_run.py, OSWorld venv).

Same loop as bench/cua/agent.mjs, but screenshots come from the VM (1920x1080, full resolution,
so model coordinates are screen pixels) and actions run as pyautogui code through OSWorld's
controller, the same execution path the Hermes run's `execute` tool uses. The computer tool has
no "done" action, so the final message decides: one starting with FAIL is passed to OSWorld as
its FAIL action (infeasible tasks), anything else as DONE. The transcript uses the Hermes
stream-json shape.

native=False (harness openai_fn) is the ablation: the same loop, prompt, actions and screenshots,
but the actions arrive through an ordinary function tool named `computer` instead of the native
computer tool the model was trained on, so the two runs differ only in that interface.
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

import requests

from bench.adapters.hermes import parse_transcript as _parse_hermes

MODEL = os.environ.get("OPENAI_CUA_MODEL", "gpt-6-luna")
EFFORT = os.environ.get("OPENAI_CUA_EFFORT", "medium")

PROMPT = (
    "You are operating an Ubuntu desktop (1920x1080) through the computer tool. The user's "
    "password is 'password' if anything asks for it.\n\nTask: {instruction}\n\n"
    "Work step by step: look at the screen, act, then check the result. When the task is "
    "complete, reply with a final message starting with DONE; if it cannot be done as stated, "
    "reply with a final message starting with FAIL."
)

# Computer-tool key names -> pyautogui key names.
KEYS = {"ENTER": "enter", "RETURN": "enter", "ESC": "esc", "ESCAPE": "esc", "TAB": "tab",
        "SPACE": "space", "BACKSPACE": "backspace", "DELETE": "delete", "DEL": "delete",
        "HOME": "home", "END": "end", "PAGEUP": "pageup", "PAGEDOWN": "pagedown",
        "ARROWUP": "up", "ARROWDOWN": "down", "ARROWLEFT": "left", "ARROWRIGHT": "right",
        "UP": "up", "DOWN": "down", "LEFT": "left", "RIGHT": "right", "CTRL": "ctrl",
        "CONTROL": "ctrl", "SHIFT": "shift", "ALT": "alt", "OPTION": "alt", "CMD": "win",
        "META": "win", "SUPER": "win", "WIN": "win"}


# The native computer tool's actions, offered as a plain function (native=False). Same action
# objects, so pyautogui_code() runs both, and one call carries a batch, as computer_call does.
_POINT = {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
          "required": ["x", "y"]}
FUNCTION_TOOL = {
    "type": "function", "name": "computer", "strict": False,
    "description": "Act on the screen. Runs the actions in order, then returns a new screenshot "
                   "(1920x1080; coordinates are screen pixels).",
    "parameters": {"type": "object", "required": ["actions"], "properties": {"actions": {
        "type": "array", "items": {"type": "object", "required": ["type"], "properties": {
            "type": {"type": "string", "enum": ["click", "double_click", "move", "scroll", "drag", "type",
                                                "keypress", "wait", "screenshot"]},
            "x": {"type": "integer"}, "y": {"type": "integer"},
            "button": {"type": "string", "enum": ["left", "right", "middle"]},
            "scroll_x": {"type": "integer", "description": "pixels"},
            "scroll_y": {"type": "integer", "description": "pixels, positive = down"},
            "path": {"type": "array", "items": _POINT, "description": "drag: start point, then points to move through"},
            "text": {"type": "string"},
            "keys": {"type": "array", "items": {"type": "string"}, "description": "pressed together, e.g. [\"CTRL\", \"S\"]"},
            "ms": {"type": "integer"}}}}}},
}


def _key(k: str) -> str:
    return KEYS.get(str(k).upper(), str(k).lower())


def pyautogui_code(a: dict) -> str:
    t = a.get("type")
    if t == "click":
        button = a.get("button", "left")
        button = button if button in ("left", "right", "middle") else "left"
        return f"pyautogui.click({a['x']}, {a['y']}, button={button!r})"
    if t == "double_click":
        return f"pyautogui.doubleClick({a['x']}, {a['y']})"
    if t == "move":
        return f"pyautogui.moveTo({a['x']}, {a['y']})"
    if t == "scroll":  # the tool gives pixels; pyautogui scrolls in wheel clicks (about 50 px each)
        def clicks(px: float) -> int:
            return round(px / 50) or (1 if px > 0 else -1)
        code = f"pyautogui.moveTo({a.get('x', 960)}, {a.get('y', 540)})"
        if a.get("scroll_y"):
            code += f"; pyautogui.scroll({-clicks(a['scroll_y'])})"  # pyautogui: positive = up
        if a.get("scroll_x"):
            code += f"; pyautogui.hscroll({clicks(a['scroll_x'])})"
        return code
    if t == "drag":
        p = a.get("path") or []
        if not p:
            return "pass"
        moves = "; ".join(f"pyautogui.moveTo({q['x']}, {q['y']}, duration=0.1)" for q in p[1:])
        return f"pyautogui.moveTo({p[0]['x']}, {p[0]['y']}); pyautogui.mouseDown(); {moves}; pyautogui.mouseUp()"
    if t == "type":
        return f"pyautogui.write({a.get('text', '')!r}, interval=0.02)"
    if t == "keypress":
        keys = [_key(k) for k in a.get("keys", [])]
        return f"pyautogui.hotkey({', '.join(repr(k) for k in keys)})" if keys else "pass"
    if t == "wait":
        return f"time.sleep({a.get('ms', 1000) / 1000})"
    if t == "screenshot":
        return "pass"
    raise ValueError(f"unknown action {t}")


def _post(body: dict, headers: dict, deadline: float) -> dict:
    """POST /v1/responses, retrying rate limits, server errors, network blips and non-JSON replies
    (a gateway error page). Quota errors are not retried: they won't clear within a task, and the
    error text lets bench.limits recognize the attempt as unscored."""
    for n in range(4):
        last = n == 3
        try:
            r = requests.post("https://api.openai.com/v1/responses", headers=headers, json=body,
                              timeout=max(10, deadline - time.monotonic()))
            d = r.json()
        except (requests.ConnectionError, ValueError):
            if last:
                raise
            time.sleep(2 * 2 ** n)
            continue
        if r.ok:
            return d
        err = d.get("error") or {}
        if last or r.status_code not in (429, 500, 502, 503) or err.get("code") == "insufficient_quota":
            raise RuntimeError(f"API {r.status_code}: {json.dumps(err or d)[:300]}")
        try:
            wait = float(r.headers.get("retry-after", ""))
        except ValueError:
            wait = 2 * 2 ** n
        time.sleep(min(wait, 60))
    raise AssertionError("unreachable")


def parse_transcript(path: Path) -> dict:
    """Hermes-shaped fields (model = the one requested), plus served_model: what the API reports
    having run, which can be a dated snapshot of the requested name."""
    res = _parse_hermes(path)
    res["served_model"] = None
    for line in path.read_text(errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "result":
            res["served_model"] = ev.get("model")
    return res


def run(controller, instruction: str, attempt: Path, budget_s: int, max_steps: int, native: bool = True) -> dict:
    """Drive the VM until the model stops; returns {status, exit_code, timed_out, steps_exhausted,
    safety_check}. native=False offers the actions as a function tool (see the module docstring)."""
    deadline = time.monotonic() + budget_s
    transcript = (attempt / "transcript.jsonl").open("w")

    def emit(ev: dict) -> None:
        transcript.write(json.dumps({**ev, "timestamp": int(time.time() * 1000)}) + "\n")
        transcript.flush()

    shots = 0

    def screenshot() -> str:
        nonlocal shots
        png = controller.get_screenshot()
        if not png:
            raise RuntimeError("screenshot failed")
        (attempt / f"shot_{shots:03d}.png").write_bytes(png)
        shots += 1
        return "data:image/png;base64," + base64.b64encode(png).decode()

    headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}
    emit({"type": "system", "subtype": "init", "model": MODEL})
    usage = {"input": 0, "output": 0, "cached": 0}
    final, exit_code, timed_out, served = "", 0, False, None
    steps_exhausted, safety_check = True, False  # cleared when the model stops on its own
    tool = {"type": "computer"} if native else FUNCTION_TOOL
    call_type = "computer_call" if native else "function_call"
    body = {"model": MODEL, "tools": [tool], "reasoning": {"effort": EFFORT},
            "truncation": "auto", "input": [{"role": "user", "content": PROMPT.format(instruction=instruction)}]}
    try:
        for _ in range(max_steps):
            if time.monotonic() > deadline:
                timed_out, steps_exhausted = True, False
                break
            d = _post(body, headers, deadline)
            served = d.get("model") or served
            u = d.get("usage") or {}
            usage["input"] += u.get("input_tokens", 0)
            usage["output"] += u.get("output_tokens", 0)
            usage["cached"] += (u.get("input_tokens_details") or {}).get("cached_tokens", 0)
            for o in d["output"]:
                if o["type"] == "message":
                    text = "".join(c.get("text", "") for c in o.get("content", []))
                    if text:
                        final = text
                        emit({"type": "text", "text": text})
            calls = [o for o in d["output"] if o["type"] == call_type]
            if not calls:
                steps_exhausted = False
                break
            outputs = []
            for call in calls:
                if call.get("pending_safety_checks"):  # nobody to approve them in a benchmark run
                    safety_check, steps_exhausted = True, False
                    emit({"type": "safety_check", "checks": call["pending_safety_checks"]})
                    raise RuntimeError(f"pending safety check: {json.dumps(call['pending_safety_checks'])[:300]}")
                if native:
                    actions = call.get("actions", [])
                else:
                    try:
                        actions = json.loads(call.get("arguments") or "{}").get("actions") or []
                    except ValueError:
                        actions = []
                for a in actions:
                    emit({"type": "tool_use", "name": f"computer.{a.get('type')}", "input": a})
                    code = pyautogui_code(a)
                    with (attempt / "actions.jsonl").open("a") as f:
                        f.write(json.dumps({"t": time.time(), "action": a, "code": code}) + "\n")
                    if code != "pass":
                        controller.execute_python_command(code)
                time.sleep(0.5)
                if native:
                    outputs.append({"type": "computer_call_output", "call_id": call["call_id"],
                                    "output": {"type": "computer_screenshot", "image_url": screenshot(),
                                               "detail": "original"}})
                else:
                    outputs.append({"type": "function_call_output", "call_id": call["call_id"],
                                    "output": [{"type": "input_image", "image_url": screenshot(),
                                                "detail": "original"}]})
            body = {**body, "input": outputs, "previous_response_id": d["id"]}
    except Exception as e:
        exit_code, steps_exhausted = 1, False
        emit({"type": "tool_result", "name": "agent", "is_error": True, "output": str(e)[:500]})
    finally:
        emit({"type": "result", "exit_code": exit_code, "text": final, "model": served,
              "tokens": {"input": usage["input"] - usage["cached"], "output": usage["output"],
                         "total": usage["input"] + usage["output"], "cache_read": usage["cached"],
                         "cache_write": 0}})
        transcript.close()
    status = "FAIL" if final.strip().upper().startswith("FAIL") else ("DONE" if final else None)
    if status:
        (attempt / "done.txt").write_text(status)
    return {"status": status, "exit_code": exit_code, "timed_out": timed_out,
            "steps_exhausted": steps_exhausted, "safety_check": safety_check}
