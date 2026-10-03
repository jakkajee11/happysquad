"""Tests for `hs hook session-start` / `hs hook stop` (spec §15, §16.1 hooks.stop_progress_nudge).

Run: python3 -m unittest discover -s evals -p 'test_hooks.py' -v
"""
import json
import os
import subprocess
import sys
import tempfile
import shutil
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
HS = os.path.join(ROOT, "bin", "hs")


def _run(w, which, env=None):
    e = dict(os.environ)
    e.pop("HS_CHILD", None)
    e.update(env or {})
    return subprocess.run([HS, "--root", w, "hook", which], cwd=w, capture_output=True, text=True, env=e)


def _happysquad_run(w, run_id, state_doc):
    d = os.path.join(w, ".happysquad", "runs", run_id)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(w, ".happysquad", "current"), "w") as f:
        f.write(run_id + "\n")
    with open(os.path.join(d, "state.json"), "w") as f:
        json.dump(state_doc, f)


def _git_repo():
    w = tempfile.mkdtemp(prefix="hs-hooks-")
    subprocess.run(["git", "init", "-q"], cwd=w, check=True)
    with open(os.path.join(w, "app.py"), "w") as f:
        f.write("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=w, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], cwd=w, check=True)
    return w


class SessionStart(unittest.TestCase):
    def setUp(self):
        self.w = tempfile.mkdtemp(prefix="hs-hooks-")

    def tearDown(self):
        shutil.rmtree(self.w, ignore_errors=True)

    def test_silent_outside_happysquad_dir(self):
        p = _run(self.w, "session-start")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")

    def test_silent_for_hs_child_even_with_in_progress_run(self):
        os.makedirs(os.path.join(self.w, ".happysquad"))
        _happysquad_run(self.w, "r1", {"state": "IMPLEMENT", "iteration": 2, "cap": 3,
                                        "task": "x", "updated_at": "2026-01-01T00:00:00Z"})
        p = _run(self.w, "session-start", env={"HS_CHILD": "1"})
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")

    def test_in_progress_nudge(self):
        os.makedirs(os.path.join(self.w, ".happysquad"))
        _happysquad_run(self.w, "r1", {"state": "IMPLEMENT", "iteration": 2, "cap": 3,
                                        "task": "x", "updated_at": "2026-01-01T00:00:00Z"})
        p = _run(self.w, "session-start")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(
            p.stdout.strip(),
            "[happysquad] in-progress run r1 at IMPLEMENT (iteration 2/3). Run /squad-resume to continue.",
        )
        self.assertTrue(os.path.isfile(os.path.join(self.w, ".happysquad", ".session")))

    def test_blocked_pointer(self):
        os.makedirs(os.path.join(self.w, ".happysquad"))
        _happysquad_run(self.w, "r1", {"state": "BLOCKED", "block_cause": "agent", "iteration": 1, "cap": 3,
                                        "task": "x", "updated_at": "2026-01-01T00:00:00Z"})
        p = _run(self.w, "session-start")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(
            p.stdout.strip(),
            "[happysquad] run r1 is BLOCKED (cause agent) — read .happysquad/runs/r1/BLOCKED.md",
        )


@unittest.skipUnless(shutil.which("git"), "needs git")
class Stop(unittest.TestCase):
    def setUp(self):
        self.w = _git_repo()

    def tearDown(self):
        shutil.rmtree(self.w, ignore_errors=True)

    def test_off_by_default_even_with_dirty_source(self):
        os.makedirs(os.path.join(self.w, ".happysquad"))
        with open(os.path.join(self.w, "app.py"), "a") as f:
            f.write("y = 2\n")
        p = _run(self.w, "stop")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stderr, "")

    def test_nudge_once_when_enabled(self):
        hsd = os.path.join(self.w, ".happysquad")
        os.makedirs(hsd)
        with open(os.path.join(hsd, "config.json"), "w") as f:
            json.dump({"hooks": {"stop_progress_nudge": True}}, f)
        with open(os.path.join(self.w, "app.py"), "a") as f:
            f.write("y = 2\n")
        p1 = _run(self.w, "stop")
        self.assertEqual(p1.returncode, 2)
        self.assertIn("Sync reminder", p1.stderr)
        p2 = _run(self.w, "stop")
        self.assertEqual(p2.returncode, 0)
        self.assertEqual(p2.stderr, "")


if __name__ == "__main__":
    unittest.main()
