"""Context checkpoint (spec §8.9): agent-tool driver only, between phases, once per session.

Run: python3 -m unittest discover -s evals -p 'test_checkpoint.py' -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
HS = os.path.join(ROOT, "bin", "hs")
TOY = os.path.join(ROOT, "evals", "fixtures", "toy-repo")
FAKE = os.path.join(ROOT, "evals", "fake_agent.py")


def _toy_repo(checkpoint=None):
    w = tempfile.mkdtemp(prefix="hs-cp-")
    shutil.copytree(TOY, w, dirs_exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=w, check=True)
    subprocess.run(["git", "add", "-A"], cwd=w, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], cwd=w, check=True)
    subprocess.run([HS, "init"], cwd=w, capture_output=True, check=True)
    cfg = {"build_cmd": "npm run build", "test_cmd": "npm test", "coverage_report": "coverage/lcov.info",
           "redgreen_cmd": "npm test -- {file}", "cap": 3}
    if checkpoint is not None:
        cfg["checkpoint"] = checkpoint
    json.dump(cfg, open(os.path.join(w, ".happysquad", "config.json"), "w"))
    return w


def _session(w, started_at="2026-10-03T10:00:00Z"):
    json.dump({"head": "x", "started_at": started_at, "nudged": False}, open(os.path.join(w, ".happysquad", ".session"), "w"))


def _hs(w, *args):
    e = dict(os.environ, HS_TOY_FAST="1")
    p = subprocess.run([HS, *args], cwd=w, capture_output=True, text=True, env=e)
    out = p.stdout.strip().splitlines()
    return json.loads(out[-1]) if out else {"action": "error", "stderr": p.stderr[-600:]}


def _drive(w, act, scenario="pass-first", max_steps=40):
    """Manual agent-tool loop like run_fake.sh. Stops at done/checkpoint/error. Returns (final, dispatches)."""
    n = 0
    e = dict(os.environ, HS_TOY_FAST="1")
    for _ in range(max_steps):
        a = act.get("action")
        if a in ("done", "checkpoint", "error"):
            return act, n
        if a == "dispatch":
            n += 1
            subprocess.run([sys.executable, FAKE, act["prompt_file"], act["out_file"], "--scenario", scenario], cwd=w, check=True, env=e)
            act = _hs(w, "advance")
        elif a == "dispatch_many":
            for d in act["dispatches"]:
                n += 1
                subprocess.run([sys.executable, FAKE, d["prompt_file"], d["out_file"], "--scenario", scenario], cwd=w, check=True, env=e)
            act = _hs(w, "advance")
        elif a == "wait":
            act = _hs(w, "wait", "--timeout", "120", "--interval", "0.5")
        else:
            act = _hs(w, "advance")
    return act, n


@unittest.skipUnless(shutil.which("node") and shutil.which("git"), "needs node + git")
class Checkpoint(unittest.TestCase):
    def setUp(self):
        self.w = None

    def tearDown(self):
        if self.w:
            shutil.rmtree(self.w, ignore_errors=True)

    def test_no_session_no_checkpoint(self):
        self.w = _toy_repo({"dispatches": 1})
        act, n = _drive(self.w, _hs(self.w, "run", "start", "t", "--driver", "agent-tool"))
        self.assertEqual(act["action"], "done", "without a hooked session the checkpoint never fires")
        self.assertEqual(act["status"], "COMPLETE")

    def test_dispatch_threshold_fires_once_between_phases(self):
        self.w = _toy_repo({"dispatches": 2, "iterations": 99})
        _session(self.w)
        act, n = _drive(self.w, _hs(self.w, "run", "start", "t", "--driver", "agent-tool"))
        self.assertEqual(act["action"], "checkpoint", act)
        self.assertEqual(n, 2, "fires after the 2nd dispatch, before the 3rd")
        self.assertTrue(os.path.isfile(os.path.join(self.w, act["handoff"])))
        txt = open(os.path.join(self.w, act["handoff"])).read()
        self.assertIn("/squad-resume", txt)
        self.assertIn(act["state"], txt)
        # same session: never again; the next call simply continues the run
        act2 = _hs(self.w, "next")
        self.assertNotEqual(act2["action"], "checkpoint")
        act3, n3 = _drive(self.w, act2)
        self.assertEqual((act3["action"], act3["status"]), ("done", "COMPLETE"))
        rid = open(os.path.join(self.w, ".happysquad", "current")).read().strip()
        evs = [json.loads(l) for l in open(os.path.join(self.w, ".happysquad", "runs", rid, "events.jsonl")) if l.strip()]
        self.assertEqual(sum(1 for e in evs if e["event"] == "checkpoint"), 1)

    def test_new_session_can_checkpoint_again(self):
        self.w = _toy_repo({"dispatches": 1, "iterations": 99})
        _session(self.w, "2026-10-03T10:00:00Z")
        act, _ = _drive(self.w, _hs(self.w, "run", "start", "t", "--driver", "agent-tool"))
        self.assertEqual(act["action"], "checkpoint")
        _session(self.w, "2026-10-03T11:00:00Z")  # a fresh session (hook rewrote .session)
        act2, _ = _drive(self.w, _hs(self.w, "resume"))
        self.assertEqual(act2["action"], "checkpoint", "a new session gets its own hand-off point")

    def test_headless_never_checkpoints(self):
        self.w = _toy_repo({"dispatches": 1})
        _session(self.w)
        e = dict(os.environ, HS_TOY_FAST="1", HS_CLAUDE=os.path.join(ROOT, "evals", "fake_claude.py"), FAKE_SCENARIO="pass-first")
        p = subprocess.run([HS, "run", "start", "t", "--driver", "fake", "--no-isolate"], cwd=self.w, capture_output=True, text=True, env=e)
        act = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual((act["action"], act["status"]), ("done", "COMPLETE"), act)

    def test_disabled(self):
        self.w = _toy_repo({"enabled": False, "dispatches": 1})
        _session(self.w)
        act, _ = _drive(self.w, _hs(self.w, "run", "start", "t", "--driver", "agent-tool"))
        self.assertEqual(act["action"], "done")


if __name__ == "__main__":
    unittest.main()
