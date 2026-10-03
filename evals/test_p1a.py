"""Unit tests for P1a pure/near-pure functions (spec §7.4 conflict, §7.6 risk, §8.3 convergence,
§20 coverage delta). Stdlib only; git-backed cases build throwaway temp repos.

Run: python3 -m unittest discover -s evals -p 'test_p1a.py' -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from hs import coverage, gates, machine, risk  # noqa: E402


def _git(root, *args, check=True):
    p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), p.stderr))
    return p.stdout


def _commit_all(root, msg):
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", msg)


# --- A. ready_workstreams -----------------------------------------------------

class ReadyWorkstreams(unittest.TestCase):
    def test_no_deps_all_pending_ready(self):
        ws = [{"name": "a", "depends_on": [], "impl": "pending"},
              {"name": "b", "depends_on": [], "impl": "pending"}]
        self.assertEqual(sorted(machine.ready_workstreams(ws, "impl")), ["a", "b"])

    def test_linear_dep_gates_on_upstream_done(self):
        ws = [{"name": "a", "depends_on": [], "impl": "pending"},
              {"name": "b", "depends_on": ["a"], "impl": "pending"}]
        self.assertEqual(machine.ready_workstreams(ws, "impl"), ["a"])
        ws[0]["impl"] = "done"
        self.assertEqual(machine.ready_workstreams(ws, "impl"), ["b"])

    def test_diamond_dependency(self):
        ws = [{"name": "a", "depends_on": [], "impl": "pending"},
              {"name": "b", "depends_on": ["a"], "impl": "pending"},
              {"name": "c", "depends_on": ["a"], "impl": "pending"},
              {"name": "d", "depends_on": ["b", "c"], "impl": "pending"}]
        self.assertEqual(machine.ready_workstreams(ws, "impl"), ["a"])
        ws[0]["impl"] = "done"
        self.assertEqual(sorted(machine.ready_workstreams(ws, "impl")), ["b", "c"])
        ws[1]["impl"] = "done"
        self.assertEqual(machine.ready_workstreams(ws, "impl"), ["c"])
        ws[2]["impl"] = "done"
        self.assertEqual(machine.ready_workstreams(ws, "impl"), ["d"])

    def test_dispatched_not_ready_and_not_done(self):
        ws = [{"name": "a", "depends_on": [], "impl": "dispatched"},
              {"name": "b", "depends_on": ["a"], "impl": "pending"}]
        self.assertEqual(machine.ready_workstreams(ws, "impl"), [])


# --- B. fingerprint ------------------------------------------------------------

class Fingerprint(unittest.TestCase):
    def f(self, **over):
        base = {"tag": "SEC", "file": "a.py", "desc": "leaks secret"}
        base.update(over)
        return base

    def test_same_fields_same_fp(self):
        self.assertEqual(machine.fingerprint(self.f()), machine.fingerprint(self.f()))

    def test_digits_and_quotes_stripped(self):
        a, b = self.f(desc="error at line 42"), self.f(desc="error at line 43")
        self.assertEqual(machine.fingerprint(a), machine.fingerprint(b))
        c, d = self.f(desc="uses 'foo' here"), self.f(desc='uses "foo" here')
        self.assertEqual(machine.fingerprint(c), machine.fingerprint(d))

    def test_different_tag_different_fp(self):
        self.assertNotEqual(machine.fingerprint(self.f(tag="SEC")), machine.fingerprint(self.f(tag="PERF")))

    def test_long_tokens_dropped(self):
        a = self.f(desc="short desc " + "a" * 45)
        b = self.f(desc="short desc " + "b" * 45)
        self.assertEqual(machine.fingerprint(a), machine.fingerprint(b))


# --- C. converge ----------------------------------------------------------------

class Converge(unittest.TestCase):
    def blocker(self, id="R-1", tag="SEC", file="a.py", desc="d", route="implementer", **over):
        b = {"id": id, "severity": "blocker", "tag": tag, "file": file, "desc": desc, "route": route, "verify": "manual"}
        b.update(over)
        return b

    def test_fresh_blocker_tracked_no_resolve_no_repeat(self):
        fs, forced, block, resolved, repeats = machine.converge({}, [self.blocker()], 1, "implementer", [], 0)
        self.assertEqual(len(fs), 1)
        self.assertIsNone(forced)
        self.assertIsNone(block)
        self.assertEqual((resolved, repeats), (0, 0))

    def test_same_blocker_twice_zero_progress_forces_then_blocks(self):
        fs1, *_ = machine.converge({}, [self.blocker()], 1, "implementer", [], 0)
        _, forced, block, resolved, repeats = machine.converge(fs1, [self.blocker()], 2, "implementer", [], 0)
        self.assertEqual((resolved, repeats), (0, 1))
        self.assertEqual(forced, "architecter")
        self.assertIsNone(block)
        _, forced2, block2, *_ = machine.converge(fs1, [self.blocker()], 2, "implementer", [], 1)
        self.assertIsNone(forced2)
        self.assertEqual(block2, "two consecutive rounds resolved zero blockers")

    def test_recurs_after_architect_round_blocks(self):
        fs1, *_ = machine.converge({}, [self.blocker()], 1, "implementer", [], 0)
        _, forced, block, *_ = machine.converge(fs1, [self.blocker()], 3, "implementer", [2], 0)
        self.assertIn("architecter round", block)
        self.assertIsNone(forced)

    def test_third_seen_with_no_arch_round_forces_architecter(self):
        fs1, *_ = machine.converge({}, [self.blocker()], 1, "implementer", [], 0)
        fs2, *_ = machine.converge(fs1, [self.blocker()], 2, "implementer", [], 0)
        _, forced, block, *_ = machine.converge(fs2, [self.blocker()], 3, "implementer", [], 0)
        self.assertEqual(forced, "architecter")
        self.assertIsNone(block)

    def test_prior_id_maps_to_existing_fp_despite_desc_change(self):
        fs1, *_ = machine.converge({}, [self.blocker(id="R-1", desc="original text")], 1, "implementer", [], 0)
        new_b = self.blocker(id="R-2", desc="a totally different description now", prior_id="R-1")
        fs2, *_ = machine.converge(fs1, [new_b], 2, "implementer", [], 0)
        self.assertEqual(len(fs2), 1)
        entry = next(iter(fs2.values()))
        self.assertEqual(entry["id"], "R-1")
        self.assertEqual(entry["seen"], [1, 2])

    def test_gate_blockers_ignored(self):
        gate_b = self.blocker(id="G-TESTS", source="gate")
        fs, forced, block, resolved, repeats = machine.converge({}, [gate_b], 1, "implementer", [], 0)
        self.assertEqual(fs, {})
        self.assertEqual((forced, block, resolved, repeats), (None, None, 0, 0))

    def test_disappeared_blocker_resolves(self):
        fs1, *_ = machine.converge({}, [self.blocker()], 1, "implementer", [], 0)
        _, forced, block, resolved, _ = machine.converge(fs1, [], 2, "implementer", [], 0)
        self.assertEqual(resolved, 1)
        self.assertIsNone(forced)
        self.assertIsNone(block)


# --- D. coverage.delta_for / parse_lcov / parse_cobertura ----------------------

class DeltaCoverage(unittest.TestCase):
    ROOT = "/repo"

    def test_added_lines_all_hit_is_100(self):
        cov = {"lines": {"src/a.js": {1: 1, 2: 1, 3: 0}}}
        got = coverage.delta_for(cov, ["src/a.js"], self.ROOT, {"src/a.js": {1, 2}})
        self.assertEqual(got["src/a.js"], 100.0)

    def test_half_hit_is_50(self):
        cov = {"lines": {"src/a.js": {1: 1, 3: 0}}}
        got = coverage.delta_for(cov, ["src/a.js"], self.ROOT, {"src/a.js": {1, 3}})
        self.assertEqual(got["src/a.js"], 50.0)

    def test_added_lines_with_no_executable_line_is_100(self):
        cov = {"lines": {"src/a.js": {1: 1}}}
        got = coverage.delta_for(cov, ["src/a.js"], self.ROOT, {"src/a.js": {99}})
        self.assertEqual(got["src/a.js"], 100.0)

    def test_no_per_line_data_with_diff_set_is_none(self):
        cov = {"lines": {}, "per_file": {}}
        got = coverage.delta_for(cov, ["src/b.js"], self.ROOT, {"src/b.js": {1, 2}})
        self.assertIsNone(got["src/b.js"])

    def test_no_per_line_data_with_all_and_per_file_pct(self):
        cov = {"lines": {}, "per_file": {"src/c.js": 73.5}}
        got = coverage.delta_for(cov, ["src/c.js"], self.ROOT, {"src/c.js": "all"})
        self.assertEqual(got["src/c.js"], 73.5)

    def test_parse_lcov_lines_and_pct(self):
        d = tempfile.mkdtemp(prefix="hs-lcov-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        p = os.path.join(d, "lcov.info")
        with open(p, "w") as f:
            f.write("SF:src/a.js\nDA:1,1\nDA:2,0\nDA:3,2\nend_of_record\n")
        c = coverage.parse_lcov(p)
        self.assertEqual(c["lines"], {"src/a.js": {1: 1, 2: 0, 3: 2}})
        self.assertAlmostEqual(c["per_file"]["src/a.js"], 66.67, places=2)

    def test_parse_cobertura_lines(self):
        d = tempfile.mkdtemp(prefix="hs-cob-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        p = os.path.join(d, "cov.xml")
        with open(p, "w") as f:
            f.write('<?xml version="1.0"?><coverage line-rate="0.5"><packages><package><classes>'
                    '<class filename="src/a.py"><lines><line number="1" hits="1"/><line number="2" hits="0"/>'
                    '</lines></class></classes></package></packages></coverage>')
        c = coverage.parse_cobertura(p)
        self.assertEqual(c["lines"], {"src/a.py": {1: 1, 2: 0}})


# --- E. gates.ownership_check --------------------------------------------------

class OwnershipCheck(unittest.TestCase):
    def test_owned_glob_match(self):
        ws = [{"name": "a", "owned": ["src/a/**"]}]
        self.assertEqual(gates.ownership_check(".", ["src/a/x.js"], ws, {}, []), [])

    def test_test_owned_glob_match(self):
        ws = [{"name": "a", "owned": []}]
        self.assertEqual(gates.ownership_check(".", ["test/a/t.js"], ws, {"a": ["test/a/**"]}, []), [])

    def test_unowned(self):
        ws = [{"name": "a", "owned": ["src/a/**"]}]
        v = gates.ownership_check(".", ["random.js"], ws, {}, [])
        self.assertEqual(v, [{"file": "random.js", "owners": [], "reason": "unowned"}])

    def test_multi_owner(self):
        ws = [{"name": "a", "owned": ["src/**"]}, {"name": "b", "owned": ["src/x.js"]}]
        v = gates.ownership_check(".", ["src/x.js"], ws, {}, [])
        self.assertEqual(v, [{"file": "src/x.js", "owners": ["a", "b"], "reason": "multi-owner"}])

    def test_generated_exempt(self):
        ws = [{"name": "a", "owned": ["src/**"]}]
        self.assertEqual(gates.ownership_check(".", ["dist/bundle.js"], ws, {}, ["dist/**"]), [])

    def test_exact_filename_match_beats_glob_misparse(self):
        # "[archive]" is a glob char-class to fnmatch, so fnmatch() alone would reject this
        # literal filename; the `f == g` fallback in ownership_check must still match it.
        ws = [{"name": "a", "owned": ["data[archive].csv"]}]
        self.assertFalse(__import__("fnmatch").fnmatch("data[archive].csv", "data[archive].csv"))
        v = gates.ownership_check(".", ["data[archive].csv"], ws, {}, [])
        self.assertEqual(v, [])


# --- F. risk.detect / load_patterns --------------------------------------------

class RiskDetect(unittest.TestCase):
    PATTERNS = {
        "sec": {"paths": ["(?i)auth"], "manifests": ["package.json"], "diff": []},
        "perf": {"paths": [], "manifests": [], "diff": ["SELECT \\* FROM"]},
    }

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hs-risk-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        _git(self.root, "init", "-q")
        with open(os.path.join(self.root, "README.md"), "w") as f:
            f.write("init\n")
        _commit_all(self.root, "init")
        os.makedirs(os.path.join(self.root, "src"))
        os.makedirs(os.path.join(self.root, "db"))
        with open(os.path.join(self.root, "src", "auth.js"), "w") as f:
            f.write("module.exports = {};\n")
        with open(os.path.join(self.root, "package.json"), "w") as f:
            f.write("{}\n")
        with open(os.path.join(self.root, "db", "query.js"), "w") as f:
            f.write('const q = "SELECT * FROM users";\n')
        with open(os.path.join(self.root, "random.txt"), "w") as f:
            f.write("nothing interesting\n")

    def _detect(self):
        return risk.detect(self.root, "HEAD", files=["src/auth.js", "package.json", "db/query.js", "random.txt"],
                           patterns=self.PATTERNS)

    def test_path_match(self):
        res = self._detect()
        m = [x for x in res["matches"] if x["file"] == "src/auth.js"]
        self.assertEqual(m, [{"file": "src/auth.js", "axis": "sec", "kind": "path", "pattern": "(?i)auth"}])

    def test_manifest_match(self):
        res = self._detect()
        m = [x for x in res["matches"] if x["file"] == "package.json"]
        self.assertEqual(m, [{"file": "package.json", "axis": "sec", "kind": "manifest", "pattern": "package.json"}])

    def test_diff_match(self):
        res = self._detect()
        m = [x for x in res["matches"] if x["file"] == "db/query.js"]
        self.assertEqual(len(m), 1)
        self.assertEqual((m[0]["axis"], m[0]["kind"]), ("perf", "diff"))

    def test_no_match_file_absent_from_matches(self):
        res = self._detect()
        self.assertFalse(any(x["file"] == "random.txt" for x in res["matches"]))
        self.assertEqual(res["axes"], ["perf", "sec"])


class RiskLoadPatterns(unittest.TestCase):
    def test_user_override_disables_one_key_leaves_rest(self):
        root = tempfile.mkdtemp(prefix="hs-riskcfg-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        os.makedirs(os.path.join(root, ".happysquad"))
        with open(os.path.join(root, ".happysquad", "risk-patterns.json"), "w") as f:
            json.dump({"sec": {"paths": []}}, f)
        pats = risk.load_patterns(root)
        self.assertEqual(pats["sec"]["paths"], [])
        self.assertTrue(pats["sec"]["manifests"])  # untouched key survives
        self.assertTrue(pats["perf"]["paths"])  # untouched axis survives


# --- G. gates.added_line_numbers ------------------------------------------------

class AddedLineNumbers(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hs-added-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        _git(self.root, "init", "-q")
        with open(os.path.join(self.root, "src.py"), "w") as f:
            f.write("L1\nL2\nL3\n")
        _commit_all(self.root, "init")

    def test_new_file_is_all(self):
        with open(os.path.join(self.root, "new.py"), "w") as f:
            f.write("x\n")
        self.assertEqual(gates.added_line_numbers(self.root, "HEAD", "new.py"), "all")

    def test_modified_file_exact_added_lines(self):
        with open(os.path.join(self.root, "src.py"), "w") as f:
            f.write("L1\nNEW1\nNEW2\nL2\nL3\n")
        self.assertEqual(gates.added_line_numbers(self.root, "HEAD", "src.py"), {2, 3})

    def test_unchanged_file_is_empty_set(self):
        self.assertEqual(gates.added_line_numbers(self.root, "HEAD", "src.py"), set())


# --- H. machine.verdict additions -----------------------------------------------

class VerdictAdditions(unittest.TestCase):
    REF = "5c56f8c26e4fe4f535adc38f012b3c36d73abea4"

    def gate(self, per_file=None, unverified=None):
        return {"tests": "pass",
                "coverage": {"status": "ok", "total": 90, "per_file": per_file or {"src/a.js": 90},
                             "unverified": unverified or []},
                "redgreen": {"ref": self.REF, "rows": [{"test": "t/a.js", "kind": "assertion"}]}}

    def test_specialist_blocker_counts_as_blocker(self):
        f = {"id": "SEC-1", "severity": "blocker", "tag": "SEC", "file": "a", "desc": "d",
             "route": "implementer", "verify": "manual", "source": "sec"}
        b, _, r = machine.verdict({"findings": [f]}, self.gate(), 80, ["src/a.js"], ["t/a.js"], self.REF)
        self.assertEqual([x["id"] for x in b], ["SEC-1"])
        self.assertEqual(r, "implementer")

    def test_cov_unverified_nonempty_is_major(self):
        b, m, _ = machine.verdict({"findings": []}, self.gate(unverified=["src/b.js"]), 80, ["src/a.js"], ["t/a.js"], self.REF)
        self.assertFalse(any(x["id"] == "G-COV" for x in b))
        maj = next(x for x in m if x["id"] == "G-COV-UNVERIFIED")
        self.assertIn("src/b.js", maj["desc"])

    def test_per_file_none_not_blocker_but_listed_unverified(self):
        b, m, _ = machine.verdict({"findings": []}, self.gate(per_file={"src/a.js": None}), 80, ["src/a.js"], ["t/a.js"], self.REF)
        self.assertFalse(any(x["id"] == "G-COV" for x in b))
        self.assertIn("G-COV-UNVERIFIED", [x["id"] for x in m])


if __name__ == "__main__":
    unittest.main()
