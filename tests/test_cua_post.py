"""bench.cua.osworld_agent._post: what is retried and how long one request may take, without the
network. Run: python3 -m unittest discover tests"""

import time
import unittest
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


if __name__ == "__main__":
    unittest.main()
