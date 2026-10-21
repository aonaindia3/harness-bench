"""OpenAI computer-use agent on the OSWorld VM (run inside bench/osworld_run.py, OSWorld venv).

Same loop as bench/cua/agent.mjs, but screenshots come from the VM (1920x1080, full resolution,
so model coordinates are screen pixels) and actions run as pyautogui code through OSWorld's
controller, the same execution path the Hermes run's `execute` tool uses. The computer tool has
no "done" action, so the final message decides: one starting with FAIL is passed to OSWorld as
its FAIL action (infeasible tasks), anything else as DONE. The transcript uses the Hermes
stream-json shape.
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

import requests

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


def run(controller, instruction: str, attempt: Path, budget_s: int, max_steps: int) -> dict:
    """Drive the VM until the model stops; returns {status, exit_code, timed_out}."""
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
    final, exit_code, timed_out = "", 0, False
    body = {"model": MODEL, "tools": [{"type": "computer"}], "reasoning": {"effort": EFFORT},
            "truncation": "auto", "input": [{"role": "user", "content": PROMPT.format(instruction=instruction)}]}
    try:
        for _ in range(max_steps):
            if time.monotonic() > deadline:
                timed_out = True
                break
            for attempt_n in range(4):  # retry rate limits, server errors and network blips
                try:
                    r = requests.post("https://api.openai.com/v1/responses", headers=headers, json=body,
                                      timeout=max(10, deadline - time.monotonic()))
                except requests.ConnectionError:
                    if attempt_n == 3:
                        raise
                    time.sleep(2 * 2 ** attempt_n)
                    continue
                if r.ok or r.status_code not in (429, 500, 502, 503) or attempt_n == 3:
                    break
                time.sleep(2 * 2 ** attempt_n)
            d = r.json()
            if not r.ok:
                raise RuntimeError(f"API {r.status_code}: {json.dumps(d.get('error', d))[:300]}")
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
            calls = [o for o in d["output"] if o["type"] == "computer_call"]
            if not calls:
                break
            outputs = []
            for call in calls:
                if call.get("pending_safety_checks"):  # nobody to approve them in a benchmark run
                    raise RuntimeError(f"pending safety check: {json.dumps(call['pending_safety_checks'])[:300]}")
                for a in call.get("actions", []):
                    emit({"type": "tool_use", "name": f"computer.{a.get('type')}", "input": a})
                    code = pyautogui_code(a)
                    with (attempt / "actions.jsonl").open("a") as f:
                        f.write(json.dumps({"t": time.time(), "action": a, "code": code}) + "\n")
                    if code != "pass":
                        controller.execute_python_command(code)
                time.sleep(0.5)
                outputs.append({"type": "computer_call_output", "call_id": call["call_id"],
                                "output": {"type": "computer_screenshot", "image_url": screenshot(),
                                           "detail": "original"}})
            body = {**body, "input": outputs, "previous_response_id": d["id"]}
    except Exception as e:
        exit_code = 1
        emit({"type": "tool_result", "name": "agent", "is_error": True, "output": str(e)[:500]})
    finally:
        emit({"type": "result", "exit_code": exit_code, "text": final,
              "tokens": {"input": usage["input"] - usage["cached"], "output": usage["output"],
                         "total": usage["input"] + usage["output"], "cache_read": usage["cached"],
                         "cache_write": 0}})
        transcript.close()
    status = "FAIL" if final.strip().upper().startswith("FAIL") else ("DONE" if final else None)
    if status:
        (attempt / "done.txt").write_text(status)
    return {"status": status, "exit_code": exit_code, "timed_out": timed_out}
