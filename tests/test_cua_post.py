"""bench.cua.osworld_agent without the network or a VM: what _post retries and how long one request
may take, and how the function-tool loop handles actions that don't exist.
Run: python3 -m unittest discover tests"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import requests

from bench.cua import osworld_agent


class Reply:
    def __init__(self, status: int, data: dict):
        self.status_code, self.ok, self._data, self.headers = status, status < 400, data, {}

    def json(self):
        return self._data


class Post(unittest.TestCase):
    def call(self, *effects):
        with mock.patch.object(requests, "post", side_effect=list(effects)) as post, \
                mock.patch.object(osworld_agent.time, "sleep"):
            out = osworld_agent._post({}, {}, time.monotonic() + 900)
        return out, post

    def test_timeout_is_retried(self):
        out, post = self.call(requests.ReadTimeout(), Reply(200, {"id": "r1"}))
        self.assertEqual(out, {"id": "r1"})
        self.assertEqual(post.call_count, 2)

    def test_request_timeout_is_capped(self):
        _, post = self.call(Reply(200, {"id": "r1"}))
        self.assertLessEqual(post.call_args.kwargs["timeout"], osworld_agent.REQUEST_TIMEOUT_S)

    def test_quota_is_not_retried(self):
        with self.assertRaisesRegex(RuntimeError, "insufficient_quota"):
            self.call(Reply(429, {"error": {"code": "insufficient_quota"}}))

    def test_gives_up_after_four_timeouts(self):
        with self.assertRaises(requests.Timeout):
            self.call(*[requests.ReadTimeout()] * 4)


class FakeVM:
    def __init__(self):
        self.commands = []

    def get_screenshot(self):
        return b"png"

    def execute_python_command(self, code):
        self.commands.append(code)


class FunctionToolLoop(unittest.TestCase):
    def test_unknown_action_is_reported_to_the_model(self):
        actions = [{"type": "click", "x": 1, "y": 2}, {"type": "right_click", "x": 3, "y": 4},
                   {"type": "type", "text": "not run"}]
        replies = [
            {"id": "r1", "model": "m", "output": [{"type": "function_call", "call_id": "c1", "name": "computer",
                                                   "arguments": json.dumps({"actions": actions})}]},
            {"id": "r2", "model": "m", "output": [{"type": "message", "content": [{"text": "DONE fixed it"}]}]},
        ]
        vm, attempt = FakeVM(), Path(tempfile.mkdtemp())
        with mock.patch.object(osworld_agent, "_post", side_effect=replies) as post, \
                mock.patch.object(osworld_agent.time, "sleep"), mock.patch.dict(os.environ, {"OPENAI_API_KEY": "k"}):
            out = osworld_agent.run(vm, "task", attempt, 900, 10, native=False)
        self.assertEqual(out["status"], "DONE")
        self.assertEqual(out["exit_code"], 0)
        self.assertEqual(vm.commands, ["pyautogui.click(1, 2, button='left')"])  # stopped at the bad action
        sent = post.call_args_list[1].args[0]["input"][0]
        self.assertEqual(sent["type"], "function_call_output")
        self.assertIn("right_click", sent["output"][0]["text"])
        self.assertEqual(sent["output"][1]["type"], "input_image")


if __name__ == "__main__":
    unittest.main()
