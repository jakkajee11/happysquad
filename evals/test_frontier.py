"""hs frontier (spec §12, 1.1): local tracker parsing, github parsing (mocked), fleet --frontier/--drain.

Run: python3 -m unittest discover -s evals -p 'test_frontier.py' -v
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

from hs import frontier as F  # noqa: E402


def _issue(n, status="ready-for-agent", blocked_by="none", labels=""):
    lines = ["# Issue %d" % n, "", "Status: %s" % status, "Blocked by: %s" % blocked_by]
    if labels:
        lines.append("Labels: %s" % labels)
    lines += ["", "**What to build:**", "Do thing %d." % n, ""]
    return "\n".join(lines)


class LocalTracker(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hs-frontier-")
        os.makedirs(os.path.join(self.root, "docs", "agents"), exist_ok=True)
        with open(os.path.join(self.root, "docs", "agents", "issue-tracker.md"), "w") as f:
            f.write("type: local\n")
        self.issues = os.path.join(self.root, ".scratch", "x", "issues")
        os.makedirs(self.issues, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, n, **kw):
        with open(os.path.join(self.issues, "%d.md" % n), "w") as f:
            f.write(_issue(n, **kw))

    def test_frontier_filters_blocked_and_passed(self):
        self._write(1)
        self._write(2, blocked_by="#1")
        self._write(3, labels="squad:passed")
        r = F.read(self.root)
        self.assertEqual(r["tracker"], "local")
        self.assertEqual([t["ref"] for t in r["frontier"]], [".scratch/x/issues/1.md"])

    def test_unblocking_moves_frontier(self):
        self._write(1)
        self._write(2, blocked_by="#1")
        # mark #1 done by rewriting Status
        self._write(1, status="done")
        r = F.read(self.root)
        self.assertEqual([t["ref"] for t in r["frontier"]], [".scratch/x/issues/2.md"])

    def test_mark_passed_drops_ticket_from_frontier(self):
        self._write(1)
        r = F.read(self.root)
        ref = r["frontier"][0]["ref"]
        F.mark_passed(self.root, ref)
        text = open(os.path.join(self.root, ref)).read()
        self.assertIn("squad:passed", text)
        r2 = F.read(self.root)
        self.assertEqual(r2["frontier"], [])

    def test_mark_passed_appends_to_existing_labels_line(self):
        self._write(1, labels="needs-review")
        r = F.read(self.root)
        ref = r["frontier"][0]["ref"]
        F.mark_passed(self.root, ref)
        text = open(os.path.join(self.root, ref)).read()
        self.assertIn("needs-review, squad:passed", text)

    def test_no_tracker_file(self):
        shutil.rmtree(os.path.join(self.root, "docs"))
        r = F.read(self.root)
        self.assertEqual(r["tracker"], "none")
        self.assertEqual(r["frontier"], [])
        self.assertTrue(r["note"])


class GithubTracker(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hs-frontier-gh-")
        os.makedirs(os.path.join(self.root, "docs", "agents"), exist_ok=True)
        with open(os.path.join(self.root, "docs", "agents", "issue-tracker.md"), "w") as f:
            f.write("type: github\n")
        self._orig_run = F._run

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        F._run = self._orig_run

    def test_parses_and_filters_squad_passed(self):
        issues = [
            {"number": 1, "title": "one", "body": "do one.\nBlocked by: none", "labels": [{"name": "ready-for-agent"}]},
            {"number": 2, "title": "two", "body": "do two.\nBlocked by: #1", "labels": [{"name": "ready-for-agent"}]},
            {"number": 3, "title": "three", "body": "done already", "labels": [{"name": "squad:passed"}]},
        ]

        def fake_run(argv, cwd):
            if argv[:3] == ["gh", "issue", "list"]:
                return subprocess.CompletedProcess(argv, 0, json.dumps(issues), "")
            if argv[:3] == ["gh", "issue", "view"]:
                n = int(argv[3])
                state = "OPEN" if n != 1 else "CLOSED"
                return subprocess.CompletedProcess(argv, 0, json.dumps({"state": state, "labels": []}), "")
            return subprocess.CompletedProcess(argv, 1, "", "unexpected call")

        F._run = fake_run
        r = F.read(self.root)
        self.assertEqual(r["tracker"], "github")
        self.assertEqual(sorted(t["ref"] for t in r["tickets"]), ["#1", "#2"])  # #3 dropped (squad:passed)
        self.assertEqual([t["ref"] for t in r["frontier"]], ["#1", "#2"])  # #1's blocker (none); #2 blocked by #1 which is CLOSED

    def test_gh_failure_yields_note(self):
        F._run = lambda argv, cwd: subprocess.CompletedProcess(argv, 1, "", "gh: command not found")
        r = F.read(self.root)
        self.assertEqual(r["tracker"], "github")
        self.assertEqual(r["frontier"], [])
        self.assertIn("gh issue list failed", r["note"])


def _toy_repo():
    w = tempfile.mkdtemp(prefix="hs-frontier-fleet-")
    shutil.copytree(TOY, w, dirs_exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=w, check=True)
    subprocess.run(["git", "add", "-A"], cwd=w, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], cwd=w, check=True)
    subprocess.run([HS, "init"], cwd=w, capture_output=True, check=True)
    json.dump({"build_cmd": "npm run build", "test_cmd": "npm test", "coverage_report": "coverage/lcov.info",
               "redgreen_cmd": "npm test -- {file}", "interactive": False, "cap": 3},
              open(os.path.join(w, ".happysquad", "config.json"), "w"))
    os.makedirs(os.path.join(w, "docs", "agents"), exist_ok=True)
    with open(os.path.join(w, "docs", "agents", "issue-tracker.md"), "w") as f:
        f.write("type: local\n")
    issues = os.path.join(w, ".scratch", "x", "issues")
    os.makedirs(issues, exist_ok=True)
    with open(os.path.join(issues, "1.md"), "w") as f:
        f.write(_issue(1).replace("Do thing 1.", "add mul(a,b) to calc"))
    with open(os.path.join(issues, "2.md"), "w") as f:
        f.write(_issue(2, blocked_by="#1").replace("Do thing 2.", "add div(a,b) to calc"))
    return w


def _hs(w, *args, scenario="pass-first", env=None):
    e = dict(os.environ, HS_TOY_FAST="1", HS_CLAUDE=os.path.join(ROOT, "evals", "fake_claude.py"), FAKE_SCENARIO=scenario)
    e.update(env or {})
    p = subprocess.run([HS, *args], cwd=w, capture_output=True, text=True, env=e)
    out = p.stdout.strip().splitlines()
    return json.loads(out[-1]) if out else {"action": "error", "stderr": p.stderr[-500:]}


@unittest.skipUnless(shutil.which("node") and shutil.which("git"), "needs node + git")
class FleetDrain(unittest.TestCase):
    def setUp(self):
        self.w = _toy_repo()

    def tearDown(self):
        shutil.rmtree(os.path.join(os.path.dirname(self.w), os.path.basename(self.w) + "-hs-wt"), ignore_errors=True)
        subprocess.run(["git", "worktree", "prune"], cwd=self.w, capture_output=True)
        shutil.rmtree(self.w, ignore_errors=True)

    def test_drain_runs_pumps_and_labels_both_tickets(self):
        s = _hs(self.w, "fleet", "start", "--drain")
        self.assertEqual((s["action"], s["status"]), ("fleet", "in_progress"), s)
        self.assertEqual(s["max_parallel"], 1)
        s = _hs(self.w, "fleet", "wait", "--timeout", "240", "--interval", "1")
        self.assertEqual(s["status"], "complete", s)
        self.assertEqual(s["counts"], {"COMPLETE": 2})
        self.assertEqual(len(s["children"]), 2)
        for c in s["children"]:
            self.assertTrue(c["passed"])
        for n in (1, 2):
            text = open(os.path.join(self.w, ".scratch", "x", "issues", "%d.md" % n)).read()
            self.assertIn("squad:passed", text)

    def test_empty_frontier_returns_empty_status_no_fleet_dir(self):
        for n in (1, 2):
            os.remove(os.path.join(self.w, ".scratch", "x", "issues", "%d.md" % n))
        s = _hs(self.w, "fleet", "start", "--frontier")
        self.assertEqual((s["action"], s["status"]), ("fleet", "empty"), s)
        self.assertFalse(os.path.isdir(os.path.join(self.w, ".happysquad", "fleets")))


if __name__ == "__main__":
    unittest.main()
