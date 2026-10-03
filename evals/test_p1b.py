"""P1b hardening tests: resume quiet window (HS_NOW), kill-mid-advance consistency, re-entrant consume,
headless argv construction (pure), worktree isolation, and the fake-claude headless driver end to end.

Run: python3 -m unittest discover -s evals -p 'test_p1b.py' -v
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
HS = os.path.join(ROOT, "bin", "hs")
TOY = os.path.join(ROOT, "evals", "fixtures", "toy-repo")

from hs import drivers, machine, state as S  # noqa: E402


def _toy_repo():
    w = tempfile.mkdtemp(prefix="hs-p1b-")
    shutil.copytree(TOY, w, dirs_exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=w, check=True)
    subprocess.run(["git", "add", "-A"], cwd=w, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], cwd=w, check=True)
    subprocess.run([HS, "init"], cwd=w, capture_output=True, check=True)
    json.dump({"build_cmd": "npm run build", "test_cmd": "npm test", "coverage_report": "coverage/lcov.info",
               "redgreen_cmd": "npm test -- {file}", "interactive": False, "cap": 3},
              open(os.path.join(w, ".happysquad", "config.json"), "w"))
    return w


def _hs(w, *args, env=None):
    e = dict(os.environ, HS_TOY_FAST="1")
    e.update(env or {})
    p = subprocess.run([HS, *args], cwd=w, capture_output=True, text=True, env=e)
    return json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {"action": "error", "stderr": p.stderr}


def _run_dir(w):
    rid = open(os.path.join(w, ".happysquad", "current")).read().strip()
    return os.path.join(w, ".happysquad", "runs", rid), rid


@unittest.skipUnless(shutil.which("node") and shutil.which("git"), "needs node + git")
class ResumeQuietWindow(unittest.TestCase):
    def setUp(self):
        self.w = _toy_repo()

    def tearDown(self):
        shutil.rmtree(self.w, ignore_errors=True)

    def test_live_agent_waits_quiet_agent_redispatches(self):
        t0 = {"HS_NOW": "2026-10-03T10:00:00Z"}
        a = _hs(self.w, "run", "start", "probe", "--driver", "agent-tool", env=t0)
        self.assertEqual((a["action"], a["phase"]), ("dispatch", "ARCHITECT"))
        r = _hs(self.w, "resume", env=t0)
        self.assertEqual((r["action"], r["for"]), ("wait", "agents"))
        r = _hs(self.w, "resume", env={"HS_NOW": "2026-10-03T10:05:00Z"})
        self.assertEqual(r["action"], "wait", "5 minutes is inside the quiet window")
        r = _hs(self.w, "resume", env={"HS_NOW": "2026-10-03T10:20:00Z"})
        self.assertEqual((r["action"], r["phase"]), ("dispatch", "ARCHITECT"))
        rd, _ = _run_dir(self.w)
        evs = [json.loads(l) for l in open(os.path.join(rd, "events.jsonl"))]
        quiet = [e for e in evs if e["event"] == "resume" and e["data"].get("quiet")]
        self.assertEqual(len(quiet), 1)
        self.assertEqual(sum(1 for e in evs if e["event"] == "dispatch"), 2)

    def test_output_on_disk_is_recovered_not_redispatched(self):
        a = _hs(self.w, "run", "start", "probe", "--driver", "agent-tool")
        pf, of = a["prompt_file"], a["out_file"]
        subprocess.run([sys.executable, os.path.join(ROOT, "evals", "fake_agent.py"), pf, of, "--scenario", "pass-first"],
                       cwd=self.w, check=True, env=dict(os.environ, HS_TOY_FAST="1"))
        r = _hs(self.w, "resume")
        self.assertEqual((r["action"], r["phase"]), ("dispatch", "IMPLEMENT"))
        rd, _ = _run_dir(self.w)
        evs = [json.loads(l) for l in open(os.path.join(rd, "events.jsonl"))]
        self.assertTrue(any(e["event"] == "recover" for e in evs))
        self.assertEqual(sum(1 for e in evs if e["event"] == "dispatch" and e.get("phase") == "ARCHITECT"), 1)


@unittest.skipUnless(shutil.which("node") and shutil.which("git"), "needs node + git")
class KillMidAdvance(unittest.TestCase):
    def setUp(self):
        self.w = _toy_repo()

    def tearDown(self):
        shutil.rmtree(self.w, ignore_errors=True)

    def test_sigkill_during_advance_leaves_consistent_state(self):
        """Run advance() under a child that dies right after the event append; state must still load,
        events.jsonl must be line-valid, and a second advance must not consume twice."""
        a = _hs(self.w, "run", "start", "probe", "--driver", "agent-tool")
        subprocess.run([sys.executable, os.path.join(ROOT, "evals", "fake_agent.py"), a["prompt_file"], a["out_file"],
                        "--scenario", "pass-first"], cwd=self.w, check=True, env=dict(os.environ, HS_TOY_FAST="1"))
        rd, rid = _run_dir(self.w)
        # patch: make save_state kill the process the first time it is called inside advance
        code = r"""
import os, sys, signal
sys.path.insert(0, %r)
from hs import state as S, machine, config as C
orig = S.save_state
def boom(rdir, st):
    os.kill(os.getpid(), signal.SIGKILL)
S.save_state = boom
machine.advance(%r, %r, C.load(%r))
""" % (ROOT, self.w, rid, self.w)
        p = subprocess.run([sys.executable, "-c", code], cwd=self.w, capture_output=True)
        self.assertEqual(p.returncode, -signal.SIGKILL)
        st = S.load_state(rd)
        self.assertIsNotNone(st, "state.json must remain loadable")
        evs = [json.loads(l) for l in open(os.path.join(rd, "events.jsonl")) if l.strip()]
        self.assertTrue(any(e["event"] == "consume" for e in evs), "event was appended before the kill")
        # pending still lists ARCHITECT (state not saved). The orphan `consume` has no follow-up event,
        # so a second advance must REPLAY it (a crash-safe log replays unfinished work) and finish the
        # transition exactly once.
        r = _hs(self.w, "advance")
        self.assertIn(r["action"], ("dispatch", "advance", "wait"))
        evs = [json.loads(l) for l in open(os.path.join(rd, "events.jsonl")) if l.strip()]
        self.assertEqual(sum(1 for e in evs if e["event"] == "transition" and e.get("phase") == "IMPLEMENT"), 1)
        self.assertEqual(S.load_state(rd)["state"], "IMPLEMENT")
        # and a third advance must not replay again (the transition settles the consume)
        _hs(self.w, "advance")
        evs = [json.loads(l) for l in open(os.path.join(rd, "events.jsonl")) if l.strip()]
        self.assertEqual(sum(1 for e in evs if e["event"] == "transition" and e.get("phase") == "IMPLEMENT"), 1)


class HeadlessArgv(unittest.TestCase):
    def test_argv_shape_and_denylist(self):
        cfg = {"headless": {"allowed_tools": "Read,Bash", "budget_per_phase": 1.5,
                            "disallowed_tools": ["Bash(git push:*)", "Bash(rm -rf:*)"]}}
        argv = drivers.claude_argv("implementer", "sonnet", "PROMPT", cfg)
        self.assertEqual(argv[0], "claude")
        self.assertEqual(argv[argv.index("-p") + 1], "PROMPT")
        self.assertEqual(argv[argv.index("--agent") + 1], "implementer")
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "1.5")
        self.assertEqual(argv.count("--disallowedTools"), 2)
        self.assertIn("Bash(git push:*)", argv)
        agents = json.loads(argv[argv.index("--agents") + 1])
        self.assertIn("implementer", agents)
        self.assertIn("tools", agents["implementer"])
        self.assertIn("Read", agents["implementer"]["tools"])
        self.assertTrue(agents["implementer"]["prompt"].strip())

    def test_hs_claude_env_overrides_binary(self):
        os.environ["HS_CLAUDE"] = "/tmp/fakebin"
        try:
            self.assertEqual(drivers.claude_argv("tester", "sonnet", "x", {})[0], "/tmp/fakebin")
        finally:
            del os.environ["HS_CLAUDE"]

    def test_every_agent_file_parses(self):
        for a in ("architecter", "implementer", "tester", "reviewer"):
            j = drivers.agents_json(a)
            self.assertIn(a, j)
            self.assertTrue(j[a]["prompt"])


@unittest.skipUnless(shutil.which("node") and shutil.which("git"), "needs node + git")
class HeadlessFakeDriver(unittest.TestCase):
    def setUp(self):
        self.w = _toy_repo()

    def tearDown(self):
        base = os.path.join(os.path.dirname(self.w), os.path.basename(self.w) + "-hs-wt")
        shutil.rmtree(base, ignore_errors=True)
        subprocess.run(["git", "worktree", "prune"], cwd=self.w, capture_output=True)
        shutil.rmtree(self.w, ignore_errors=True)

    def test_role_prompts_not_016_bodies(self):
        for a in ("architecter", "implementer", "tester", "reviewer", "specialist"):
            p = drivers.agents_json(a)[a]["prompt"]
            self.assertNotIn("DESIGN_READY", p)
            self.assertNotIn("Brainstorm mode", p)
            self.assertLess(len(p), 600)
        self.assertIn("Write", drivers.agents_json("reviewer")["reviewer"]["tools"])

    def test_isolated_worktree_run_completes_and_main_tree_untouched(self):
        before = subprocess.run(["git", "status", "--porcelain"], cwd=self.w, capture_output=True, text=True).stdout
        env = {"HS_CLAUDE": os.path.join(ROOT, "evals", "fake_claude.py"), "FAKE_SCENARIO": "pass-first"}
        r = _hs(self.w, "run", "start", "add mul", "--driver", "fake", env=env)
        self.assertEqual((r["action"], r["status"]), ("done", "COMPLETE"), r)
        self.assertNotIn("/.git/", r["worktree"] + "/", "worktree must not live under .git (Claude refuses writes there)")
        self.assertTrue(r["worktree"].startswith(os.path.dirname(os.path.realpath(self.w))) or r["worktree"].startswith(os.path.dirname(self.w)), r["worktree"])
        self.assertTrue(r["branch"].startswith("hs/"))
        self.wt_to_clean = r["worktree"]
        after = subprocess.run(["git", "status", "--porcelain"], cwd=self.w, capture_output=True, text=True).stdout
        self.assertEqual(before, after, "main working tree must be untouched")
        self.assertNotIn("mul", open(os.path.join(self.w, "src", "calc.js")).read())
        self.assertIn("mul", open(os.path.join(r["worktree"], "src", "calc.js")).read())
        branches = subprocess.run(["git", "branch", "--list", "hs/*"], cwd=self.w, capture_output=True, text=True).stdout
        self.assertIn(r["branch"], branches)

    def test_no_isolate_runs_in_place(self):
        env = {"HS_CLAUDE": os.path.join(ROOT, "evals", "fake_claude.py"), "FAKE_SCENARIO": "pass-first"}
        r = _hs(self.w, "run", "start", "add mul", "--driver", "fake", "--no-isolate", env=env)
        self.assertEqual((r["action"], r["status"]), ("done", "COMPLETE"), r)
        self.assertNotIn("worktree", r)
        self.assertIn("mul", open(os.path.join(self.w, "src", "calc.js")).read())


if __name__ == "__main__":
    unittest.main()
