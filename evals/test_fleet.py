"""hs fleet (spec §12) on the fake driver: scheduling, isolation, a BLOCKED sibling, resume-by-advance, cleanup.

Run: python3 -m unittest discover -s evals -p 'test_fleet.py' -v
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


def _toy_repo():
    w = tempfile.mkdtemp(prefix="hs-fleet-")
    shutil.copytree(TOY, w, dirs_exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=w, check=True)
    subprocess.run(["git", "add", "-A"], cwd=w, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], cwd=w, check=True)
    subprocess.run([HS, "init"], cwd=w, capture_output=True, check=True)
    json.dump({"build_cmd": "npm run build", "test_cmd": "npm test", "coverage_report": "coverage/lcov.info",
               "redgreen_cmd": "npm test -- {file}", "interactive": False, "cap": 3},
              open(os.path.join(w, ".happysquad", "config.json"), "w"))
    return w


def _hs(w, *args, scenario="pass-first", env=None):
    e = dict(os.environ, HS_TOY_FAST="1", HS_CLAUDE=os.path.join(ROOT, "evals", "fake_claude.py"), FAKE_SCENARIO=scenario)
    e.update(env or {})
    p = subprocess.run([HS, *args], cwd=w, capture_output=True, text=True, env=e)
    out = p.stdout.strip().splitlines()
    return json.loads(out[-1]) if out else {"action": "error", "stderr": p.stderr[-500:]}


@unittest.skipUnless(shutil.which("node") and shutil.which("git"), "needs node + git")
class Fleet(unittest.TestCase):
    def setUp(self):
        self.w = _toy_repo()

    def tearDown(self):
        shutil.rmtree(os.path.join(os.path.dirname(self.w), os.path.basename(self.w) + "-hs-wt"), ignore_errors=True)
        subprocess.run(["git", "worktree", "prune"], cwd=self.w, capture_output=True)
        shutil.rmtree(self.w, ignore_errors=True)

    def test_two_children_complete_in_isolation(self):
        s = _hs(self.w, "fleet", "start", "add mul(a,b) to calc", "add div(a,b) to calc", "--max", "2")
        self.assertEqual((s["action"], s["status"]), ("fleet", "in_progress"), s)
        self.assertEqual(s["counts"].get("in_progress"), 2)
        s = _hs(self.w, "fleet", "wait", "--timeout", "180", "--interval", "1")
        self.assertEqual(s["status"], "complete", s)
        self.assertEqual(s["counts"], {"COMPLETE": 2})
        self.assertEqual(len(s["merge"]), 2)
        for c in s["children"]:
            self.assertTrue(c["branch"].startswith("fleet/"))
            self.assertNotIn("/.git/", c["worktree"] + "/")
            self.assertTrue(os.path.isfile(os.path.join(c["worktree"], "src", "calc.js")))
        # main tree untouched
        st = subprocess.run(["git", "status", "--porcelain", "--", "src", "test"], cwd=self.w, capture_output=True, text=True).stdout
        self.assertEqual(st.strip(), "")
        self.assertNotIn("mul", open(os.path.join(self.w, "src", "calc.js")).read())
        rep = open(os.path.join(self.w, s["report"])).read()
        self.assertIn("Passed: 2", rep)
        self.assertIn("git merge --no-ff fleet/", rep)

    def test_max_parallel_is_respected(self):
        s = _hs(self.w, "fleet", "start", "t1", "t2", "t3", "--max", "1")
        self.assertEqual(s["counts"], {"in_progress": 1, "pending": 2})
        s = _hs(self.w, "fleet", "wait", "--timeout", "240", "--interval", "1")
        self.assertEqual(s["status"], "complete")
        self.assertEqual(s["counts"], {"COMPLETE": 3})

    def test_blocked_child_does_not_stall_fleet(self):
        # child 1 happy; child 2 gets the validation-blocked scenario via a per-child override is not possible
        # (one FAKE_SCENARIO per process tree), so run the whole fleet under the blocked scenario and check
        # the fleet still reaches `complete` with BLOCKED children and a report.
        s = _hs(self.w, "fleet", "start", "t1", "t2", "--max", "2", scenario="validation-blocked")
        s = _hs(self.w, "fleet", "wait", "--timeout", "180", "--interval", "1", scenario="validation-blocked")
        self.assertEqual(s["status"], "complete", s)
        self.assertEqual(s["counts"], {"BLOCKED": 2})
        self.assertEqual(s["merge"], [])
        rep = open(os.path.join(self.w, s["report"])).read()
        self.assertIn("## Blocked", rep)
        self.assertIn("BLOCKED.md", rep)

    def test_advance_is_idempotent_and_status_matches(self):
        _hs(self.w, "fleet", "start", "only task", "--max", "1")
        a = _hs(self.w, "fleet", "advance")
        b = _hs(self.w, "fleet", "status")
        self.assertEqual(a["fleet_id"], b["fleet_id"])
        self.assertEqual(a["counts"], b["counts"])
        s = _hs(self.w, "fleet", "wait", "--timeout", "120", "--interval", "1")
        self.assertEqual(s["status"], "complete")
        again = _hs(self.w, "fleet", "advance")
        self.assertEqual(again["status"], "complete")
        self.assertEqual(again["counts"], {"COMPLETE": 1})

    def test_cleanup_keeps_failed_by_default(self):
        _hs(self.w, "fleet", "start", "t1", "--max", "1", scenario="validation-blocked")
        s = _hs(self.w, "fleet", "wait", "--timeout", "120", "--interval", "1", scenario="validation-blocked")
        self.assertEqual(s["counts"], {"BLOCKED": 1})
        wt = s["children"][0]["worktree"]
        r = _hs(self.w, "fleet", "cleanup")
        self.assertEqual(r["removed"], [])
        self.assertTrue(os.path.isdir(wt))
        r = _hs(self.w, "fleet", "cleanup", "--all")
        self.assertEqual(r["removed"], ["t1"])
        self.assertFalse(os.path.isdir(wt))

    def test_tasks_file(self):
        with open(os.path.join(self.w, "tasks.txt"), "w") as f:
            f.write("# backlog\n- add mul\n\n* add div\n")
        s = _hs(self.w, "fleet", "start", "--tasks-file", "tasks.txt", "--max", "2")
        self.assertEqual(len(s["children"]), 2)
        self.assertEqual([c["slug"] for c in s["children"]], ["add-mul", "add-div"])
        s = _hs(self.w, "fleet", "wait", "--timeout", "180", "--interval", "1")
        self.assertEqual(s["counts"], {"COMPLETE": 2})


if __name__ == "__main__":
    unittest.main()
