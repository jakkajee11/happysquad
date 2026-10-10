"""`hs run review-only` (spec §14 /squad-review) on the fake driver.

Run: python3 -m unittest discover -s evals -p 'test_review_only.py' -v
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

from hs import machine  # noqa: E402


def _toy_repo():
    w = tempfile.mkdtemp(prefix="hs-ro-")
    shutil.copytree(TOY, w, dirs_exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=w, check=True)
    subprocess.run(["git", "add", "-A"], cwd=w, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], cwd=w, check=True)
    subprocess.run([HS, "init"], cwd=w, capture_output=True, check=True)
    json.dump({"build_cmd": "npm run build", "test_cmd": "npm test", "coverage_report": "coverage/lcov.info",
               "redgreen_cmd": "npm test -- {file}", "interactive": False, "cap": 3},
              open(os.path.join(w, ".happysquad", "config.json"), "w"))
    return w


def _add_mul(w):
    with open(os.path.join(w, "src", "calc.js"), "a") as f:
        f.write("\nexport function mul(a, b) {\n  return a * b;\n}\n")
    with open(os.path.join(w, "test", "mul.test.js"), "w") as f:
        f.write('import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
                'import { mul } from "../src/calc.js";\ntest("mul", () => { assert.equal(mul(3, 4), 12); });\n')


def _hs(w, *args, scenario="pass-first"):
    e = dict(os.environ, HS_TOY_FAST="1", HS_CLAUDE=os.path.join(ROOT, "evals", "fake_claude.py"), FAKE_SCENARIO=scenario)
    p = subprocess.run([HS, *args], cwd=w, capture_output=True, text=True, env=e)
    out = p.stdout.strip().splitlines()
    return json.loads(out[-1]) if out else {"action": "error", "stderr": p.stderr[-800:]}


class LooksLikeTest(unittest.TestCase):
    def test_classifier(self):
        for p in ("test/mul.test.js", "tests/test_x.py", "src/__tests__/a.ts", "pkg/a_test.go", "spec/a.spec.ts", "Backend.Tests/FooTests.cs"):
            self.assertTrue(machine._looks_like_test(p), p)
        for p in ("src/calc.js", "hs/machine.py", "README.md", "contest/rules.md"):
            self.assertFalse(machine._looks_like_test(p), p)


@unittest.skipUnless(shutil.which("node") and shutil.which("git"), "needs node + git")
class ReviewOnly(unittest.TestCase):
    def setUp(self):
        self.w = _toy_repo()

    def tearDown(self):
        shutil.rmtree(self.w, ignore_errors=True)

    def test_empty_diff_is_an_error(self):
        r = _hs(self.w, "run", "review-only", "--driver", "fake")
        self.assertEqual(r["action"], "error")
        self.assertIn("nothing to review", r["message"])

    def test_diff_is_reviewed_without_build_agents(self):
        _add_mul(self.w)
        r = _hs(self.w, "run", "review-only", "--driver", "fake", "--task", "mul added")
        self.assertEqual((r["action"], r["status"]), ("done", "COMPLETE"), r)
        self.assertEqual(r["verdict"], "PASS")
        self.assertEqual(r["blockers"], 0)
        self.assertTrue(r["report"].endswith("REVIEW-i1/review.md"))
        self.assertNotIn("suggested_commit", r)
        self.assertNotIn("wiki_offer", r)
        rid = open(os.path.join(self.w, ".happysquad", "current")).read().strip()
        self.assertIn("-review-", rid)
        evs = [json.loads(l) for l in open(os.path.join(self.w, ".happysquad", "runs", rid, "events.jsonl")) if l.strip()]
        dispatched = [e.get("phase") for e in evs if e["event"] == "dispatch"]
        self.assertEqual(dispatched, ["REVIEW"], "only the reviewer may be dispatched")
        st = json.load(open(os.path.join(self.w, ".happysquad", "runs", rid, "state.json")))
        self.assertTrue(st["review_only"])
        self.assertEqual(st["workstreams"][0]["owned"], ["src/calc.js"])
        self.assertEqual(st["test_owned"]["diff"], ["test/mul.test.js"])
        gate = json.load(open(os.path.join(self.w, ".happysquad", "runs", rid, "gates-TEST-i1.json")))
        self.assertEqual(gate["tests"], "pass")
        self.assertIn("src/calc.js", gate["coverage"]["per_file"])
        # the diff's new test file is proven red at base like a tester's would be: no G-RED-NONE
        self.assertEqual([(r["test"], r["kind"]) for r in gate["redgreen"]["rows"]], [("test/mul.test.js", "compile")])
        v = json.load(open(os.path.join(self.w, r["report"].replace("review.md", "verdict.json"))))
        self.assertNotIn("G-RED-NONE", [m["id"] for m in v["majors"]])
        prompt = open(os.path.join(self.w, ".happysquad", "runs", rid, "prompts", "REVIEW-i1.md")).read()
        self.assertNotIn("Mode `delta`", prompt)
        self.assertNotIn("(none)\n\n## Output", prompt)

    def test_new_test_green_at_base_is_a_red_first_blocker(self):
        # a "new" test that passes against the old code proves nothing about the change
        with open(os.path.join(self.w, "test", "add2.test.js"), "w") as f:
            f.write('import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
                    'import { add } from "../src/calc.js";\ntest("add2", () => { assert.equal(add(1, 1), 2); });\n')
        r = _hs(self.w, "run", "review-only", "--driver", "fake")
        self.assertEqual(r["verdict"], "FAIL", r)
        v = json.load(open(os.path.join(self.w, r["report"].replace("review.md", "verdict.json"))))
        self.assertIn("G-RED", [b["id"] for b in v["blockers"]])
        fb = open(os.path.join(self.w, r["feedback"])).read()
        self.assertTrue(fb.startswith("# Review findings  (review-only"), fb[:80])

    def test_blocker_gives_fail_verdict_and_feedback_without_routing(self):
        _add_mul(self.w)
        # review-fail-then-pass's REVIEW-i1 returns one blocker; review-only must stop there with FAIL
        r = _hs(self.w, "run", "review-only", "--driver", "fake", scenario="review-fail-then-pass")
        self.assertEqual((r["action"], r["status"]), ("done", "COMPLETE"), r)
        self.assertEqual(r["verdict"], "FAIL")
        self.assertGreaterEqual(r["blockers"], 1)
        self.assertTrue(r["feedback"] and os.path.isfile(os.path.join(self.w, r["feedback"])))
        rid = open(os.path.join(self.w, ".happysquad", "current")).read().strip()
        evs = [json.loads(l) for l in open(os.path.join(self.w, ".happysquad", "runs", rid, "events.jsonl")) if l.strip()]
        self.assertEqual(sum(1 for e in evs if e["event"] == "dispatch"), 1, "no second round after a review-only FAIL")

    def test_explicit_base(self):
        _add_mul(self.w)
        subprocess.run(["git", "add", "-A"], cwd=self.w, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "mul"], cwd=self.w, check=True)
        r = _hs(self.w, "run", "review-only", "--driver", "fake")
        self.assertEqual(r["action"], "error", "HEAD vs HEAD is empty")
        r = _hs(self.w, "run", "review-only", "--driver", "fake", "--base", "HEAD~1")
        self.assertEqual((r["action"], r["verdict"]), ("done", "PASS"), r)
        self.assertEqual(r["files_changed"], 2)


@unittest.skipUnless(shutil.which("node") and shutil.which("git"), "needs node + git")
class StartFromDesign(unittest.TestCase):
    """--design: a complete hs-design block skips the architect; a broken one falls back to it."""

    def setUp(self):
        self.w = _toy_repo()

    def tearDown(self):
        shutil.rmtree(self.w, ignore_errors=True)

    def _dispatched(self):
        rid = open(os.path.join(self.w, ".happysquad", "current")).read().strip()
        evs = [json.loads(l) for l in open(os.path.join(self.w, ".happysquad", "runs", rid, "events.jsonl")) if l.strip()]
        return [e.get("phase") for e in evs if e["event"] == "dispatch"], evs

    def test_complete_block_skips_architect(self):
        ticket = os.path.join(ROOT, "evals", "fixtures", "tickets", "mul-design.md")
        r = _hs(self.w, "run", "start", "add mul", "--driver", "fake", "--no-isolate", "--design", ticket)
        self.assertEqual((r["action"], r["status"]), ("done", "COMPLETE"), r)
        phases, evs = self._dispatched()
        self.assertNotIn("ARCHITECT", phases)
        self.assertEqual(phases[:2], ["IMPLEMENT", "TEST"])
        self.assertTrue(any(e["event"] == "design" and e["data"].get("ok") for e in evs))

    def test_block_in_the_task_text_counts(self):
        task = open(os.path.join(ROOT, "evals", "fixtures", "tickets", "mul-design.md")).read()
        r = _hs(self.w, "run", "start", task, "--driver", "fake", "--no-isolate")
        self.assertEqual(r["status"], "COMPLETE", r)
        self.assertNotIn("ARCHITECT", self._dispatched()[0])

    def test_broken_block_falls_back_to_architect(self):
        bad = os.path.join(self.w, "ticket.md")
        with open(bad, "w") as f:
            f.write('add mul\n\n```hs-design\n{"ac": [], "owned": []}\n```\n')
        r = _hs(self.w, "run", "start", "add mul", "--driver", "fake", "--no-isolate", "--design", bad)
        self.assertEqual(r["status"], "COMPLETE", r)
        phases, evs = self._dispatched()
        self.assertEqual(phases[0], "ARCHITECT")
        self.assertTrue(any(e["event"] == "design" and e["data"].get("ok") is False for e in evs))

if __name__ == "__main__":
    unittest.main()
