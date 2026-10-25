"""bench.report: how attempts ended, and per-trial totals. Run: python3 -m unittest discover tests"""

import unittest

from bench.report import compare, ended


def row(task="os/a", trial=0, success=False, **kw):
    return {"suite": "osworld", "task": task, "trial": trial, "harness": "h", "model": "m",
            "success": success, "detail": "agent said DONE", "exit_code": 0, "timed_out": False,
            "wall_s": 1.0, "tool_calls": 1, **kw}


class Ended(unittest.TestCase):
    def test_each_ending(self):
        cases = {
            "done": row(),
            "fail": row(detail="agent said FAIL"),
            "env": row(detail="setup failed: boom"),
            "time": row(detail="agent never called done", timed_out=True),
            "steps": row(detail="agent never called done", exit_code=1, steps_exhausted=True),
            "safety": row(detail="agent never called done", exit_code=1, safety_check=True),
            "error": row(detail="agent never called done", exit_code=1),
            "none": row(detail="agent never called done"),
        }
        for want, r in cases.items():
            self.assertEqual(ended(r), want, want)

    def test_evaluator_error_is_env_even_after_done(self):
        self.assertEqual(ended(row(detail="evaluate error: Postconfig setup failed", exit_code=1)), "env")

    def test_old_rows_without_new_fields(self):
        r = row(detail="agent never called done", exit_code=1)
        for k in ("trial", "steps_exhausted", "safety_check"):
            r.pop(k, None)
        self.assertEqual(ended(r), "error")


class Compare(unittest.TestCase):
    def test_per_trial_totals(self):
        rows = [row("os/a", 0, True), row("os/b", 0, False),
                row("os/a", 1, True), row("os/b", 1, True)]
        out = compare(rows)
        self.assertIn("3/4 (75%); per trial 1, 2 of 2 · mean 1.5", out)
        self.assertIn("| osworld said done, failed | 1 |", out)
        self.assertIn("| osworld | os/a | PASS |", out)
        self.assertIn("| osworld | os/b | 1/2 |", out)

    def test_single_trial_and_web_rows_unchanged(self):
        web = {"suite": "miniwob", "task": "t", "trial": 0, "harness": "h", "model": "m", "success": True,
               "wall_s": 1.0, "tool_calls": 1}
        out = compare([web])
        self.assertIn("| miniwob | 1/1 (100%) |", out)
        self.assertNotIn("per trial", out)
        self.assertNotIn("ended", out)


if __name__ == "__main__":
    unittest.main()
