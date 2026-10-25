"""bench.limits: which attempts count as stopped by a usage limit. Run: python3 -m unittest discover tests"""

import json
import tempfile
import unittest
from pathlib import Path

from bench.limits import limited


def attempt(stderr: str = "", events: list[dict] = ()) -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "stderr.log").write_text(stderr)
    (d / "transcript.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    return d


class Limited(unittest.TestCase):
    def test_plan_limit_in_stderr(self):
        a = attempt(stderr="Error: You've hit your usage limit. Try again at 9:00 PM.\n")
        self.assertIn("usage limit", limited(a, 1))

    def test_api_quota_in_agent_error(self):
        err = 'API 429: {"code": "insufficient_quota", "message": "You exceeded your current quota"}'
        a = attempt(events=[{"type": "tool_result", "name": "agent", "is_error": True, "output": err}])
        self.assertIsNotNone(limited(a, 1))

    def test_codex_turn_failed(self):
        a = attempt(events=[{"type": "turn.failed", "error": {"message": "rate_limit_exceeded"}}])
        self.assertIsNotNone(limited(a, 1))

    def test_clean_exit_never_counts(self):
        a = attempt(stderr="usage limit\n")
        self.assertIsNone(limited(a, 0))

    def test_tool_output_is_ignored(self):
        # A page or file the agent read can mention 429 or rate limits; that is not our limit.
        a = attempt(events=[{"type": "tool_result", "name": "execute", "output": "HTTP 429 Too Many Requests"},
                            {"type": "result", "exit_code": 1, "text": ""}])
        self.assertIsNone(limited(a, 1))

    def test_ordinary_crash(self):
        a = attempt(events=[{"type": "tool_result", "name": "agent", "is_error": True,
                             "output": "Expecting value: line 1 column 1 (char 0)"}])
        self.assertIsNone(limited(a, 1))

    def test_missing_files(self):
        self.assertIsNone(limited(Path(tempfile.mkdtemp()), 1))


if __name__ == "__main__":
    unittest.main()
