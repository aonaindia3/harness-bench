// Operator-style agent: OpenAI's computer tool (Responses API) driving a local Chromium.
//
//   node bench/cua/agent.mjs <task.json>
//   task.json: {prompt, url, out_dir, budget_s, model, effort, downloads, chromium}
//
// The model only sees screenshots and answers with screen actions (click x,y, type, scroll, ...);
// there is no DOM access and no JavaScript. The page in the prompt is opened before the first
// screenshot, since the computer tool has no "navigate" action. The transcript is written in the
// same stream-json shape as Hermes (system/tool_use/text/result events) so bench/adapters/hermes.py
// can parse it and bench.watch can show it. Needs OPENAI_API_KEY.

import { createRequire } from "node:module";
import { readFileSync, writeFileSync, appendFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const require = createRequire(path.join(ROOT, "vendor/playwright-mcp/package.json"));
const { chromium } = require("playwright");

const task = JSON.parse(readFileSync(process.argv[2], "utf8"));
const VIEWPORT = { width: 1280, height: 720 };
const MAX_TURNS = 60;
const deadline = Date.now() + task.budget_s * 1000;
const transcript = path.join(task.out_dir, "transcript.jsonl");
const emit = (ev) => appendFileSync(transcript, JSON.stringify({ ...ev, timestamp: Date.now() }) + "\n");

// Computer-tool key names -> Playwright key names.
const KEYS = {
  ENTER: "Enter", RETURN: "Enter", ESC: "Escape", ESCAPE: "Escape", TAB: "Tab", SPACE: " ",
  BACKSPACE: "Backspace", DELETE: "Delete", DEL: "Delete", HOME: "Home", END: "End",
  PAGEUP: "PageUp", PAGEDOWN: "PageDown", ARROWUP: "ArrowUp", ARROWDOWN: "ArrowDown",
  ARROWLEFT: "ArrowLeft", ARROWRIGHT: "ArrowRight", UP: "ArrowUp", DOWN: "ArrowDown",
  LEFT: "ArrowLeft", RIGHT: "ArrowRight", CTRL: "Control", CONTROL: "Control", SHIFT: "Shift",
  ALT: "Alt", OPTION: "Alt", CMD: "Meta", META: "Meta", SUPER: "Meta", WIN: "Meta",
};
const key = (k) => KEYS[String(k).toUpperCase()] ?? (String(k).length === 1 ? String(k) : String(k)[0].toUpperCase() + String(k).slice(1).toLowerCase());

async function act(page, a) {
  const m = page.mouse;
  switch (a.type) {
    case "click":
      if (a.button === "back") return page.goBack().catch(() => {});
      if (a.button === "forward") return page.goForward().catch(() => {});
      return m.click(a.x, a.y, { button: ["left", "right", "middle"].includes(a.button) ? a.button : "left" });
    case "double_click": return m.dblclick(a.x, a.y);
    case "move": return m.move(a.x, a.y);
    case "scroll": await m.move(a.x ?? VIEWPORT.width / 2, a.y ?? VIEWPORT.height / 2); return m.wheel(a.scroll_x ?? 0, a.scroll_y ?? 0);
    case "drag": {
      const p = a.path ?? [];
      if (!p.length) return;
      await m.move(p[0].x, p[0].y); await m.down();
      for (const q of p.slice(1)) await m.move(q.x, q.y, { steps: 5 });
      return m.up();
    }
    case "type": return page.keyboard.type(a.text ?? "", { delay: 20 });
    case "keypress": return page.keyboard.press((a.keys ?? []).map(key).join("+"));
    case "wait": return page.waitForTimeout(a.ms ?? 1000);
    case "screenshot": return;
    default: throw new Error(`unknown action ${a.type}`);
  }
}

let shotN = 0;
async function screenshot(page) {
  const png = await page.screenshot({ type: "png" });
  writeFileSync(path.join(task.out_dir, `shot_${String(shotN++).padStart(3, "0")}.png`), png);
  return `data:image/png;base64,${png.toString("base64")}`;
}

async function respond(body) {
  for (let attempt = 0; ; attempt++) {
    const r = await fetch("https://api.openai.com/v1/responses", {
      method: "POST",
      headers: { Authorization: `Bearer ${process.env.OPENAI_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(Math.max(5000, deadline - Date.now())),
    });
    const d = await r.json();
    if (r.ok) return d;
    if ((r.status === 429 || r.status >= 500) && attempt < 3 && Date.now() < deadline - 10000) {
      await new Promise((res) => setTimeout(res, 2000 * 2 ** attempt));
      continue;
    }
    throw new Error(`API ${r.status}: ${JSON.stringify(d.error ?? d).slice(0, 300)}`);
  }
}

mkdirSync(task.out_dir, { recursive: true });
writeFileSync(transcript, "");
emit({ type: "system", subtype: "init", model: task.model });
const usage = { input: 0, output: 0, cached: 0 };
let finalText = "";
let exitCode = 0;
const browser = await chromium.launch({ headless: true, executablePath: task.chromium });
try {
  const context = await browser.newContext({ viewport: VIEWPORT, acceptDownloads: true });
  const page = await context.newPage();
  page.on("download", (d) => d.saveAs(path.join(task.downloads, d.suggestedFilename())).catch(() => {}));
  await page.goto(task.url, { waitUntil: "load", timeout: 30000 });
  emit({ type: "system", subtype: "open_page", url: task.url });

  let input = [{ role: "user", content: task.prompt }];
  let previous = null;
  for (let turn = 0; turn < MAX_TURNS && Date.now() < deadline; turn++) {
    const d = await respond({
      model: task.model, tools: [{ type: "computer" }], reasoning: { effort: task.effort },
      instructions: `You operate a web browser only through the computer tool (screenshots plus mouse and keyboard). The page ${task.url} is already open; there is no address bar. When the task is complete, reply with your final answer as plain text.`,
      input, previous_response_id: previous, truncation: "auto",
    });
    previous = d.id;
    usage.input += d.usage?.input_tokens ?? 0;
    usage.output += d.usage?.output_tokens ?? 0;
    usage.cached += d.usage?.input_tokens_details?.cached_tokens ?? 0;
    const calls = d.output.filter((o) => o.type === "computer_call");
    for (const o of d.output) {
      if (o.type === "message") {
        const text = (o.content ?? []).map((c) => c.text ?? "").join("");
        if (text) { finalText = text; emit({ type: "text", text }); }
      }
    }
    if (!calls.length) break;
    input = [];
    for (const call of calls) {
      if (call.pending_safety_checks?.length) {  // nobody to approve them in a benchmark run
        emit({ type: "tool_result", name: "computer", is_error: true, output: `stopped on safety check: ${JSON.stringify(call.pending_safety_checks)}` });
        throw new Error("pending safety check");
      }
      for (const a of call.actions ?? []) {
        emit({ type: "tool_use", name: `computer.${a.type}`, input: a });
        try { await act(page, a); }
        catch (e) { emit({ type: "tool_result", name: `computer.${a.type}`, is_error: true, output: String(e).slice(0, 300) }); }
      }
      await page.waitForTimeout(300);
      input.push({ type: "computer_call_output", call_id: call.call_id,
                   output: { type: "computer_screenshot", image_url: await screenshot(page), detail: "original" } });
    }
  }
} catch (e) {
  exitCode = 1;
  emit({ type: "tool_result", name: "agent", is_error: true, output: String(e).slice(0, 500) });
} finally {
  await browser.close().catch(() => {});
  emit({ type: "result", exit_code: exitCode, text: finalText,
         tokens: { input: usage.input - usage.cached, output: usage.output, total: usage.input + usage.output,
                   cache_read: usage.cached, cache_write: 0 } });
}
process.exit(exitCode);
