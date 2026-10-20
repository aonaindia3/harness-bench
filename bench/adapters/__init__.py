"""Harness adapters.

Each adapter module exposes:

    run(prompt, workdir, out_dir, budget_s, model=None) -> dict

with keys wall_s, exit_code, timed_out, final_text, tool_calls, tools, tool_inputs,
tokens_in, tokens_out, tokens_total, tokens_cache_read (None when unknown), and optionally
model (the model actually used). An optional version() -> str is recorded in config.json.
The agent must run with `workdir` as its cwd and drive a browser to the URL in the prompt.
"""

import importlib


def load(name: str):
    return importlib.import_module(f"bench.adapters.{name}")
