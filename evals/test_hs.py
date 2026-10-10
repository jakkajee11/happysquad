"""Unit tests for the pure hs modules — no git, no model, no subprocess except provenance.run.

Run: python3 -m unittest discover -s evals -v
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from hs import coverage, machine, provenance, render, schemas  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "coverage")


def _arch(**over):
    base = {"phase": "ARCHITECT", "size": "S", "design": "design.md",
            "ac": [{"id": "AC-1", "text": "x"}, {"id": "AC-2", "text": "y"}],
            "workstreams": [{"name": "a", "owned": ["src/a.js"], "depends_on": [], "ac": ["AC-1", "AC-2"]}]}
    base.update(over)
    return base


class SchemaShape(unittest.TestCase):
    def test_valid_architect(self):
        self.assertEqual(schemas.check("ARCHITECT", _arch()), [])

    def test_missing_key_named(self):
        o = _arch()
        del o["workstreams"]
        errs = schemas.check("ARCHITECT", o)
        self.assertTrue(any("missing key 'workstreams'" in e for e in errs), errs)

    def test_unknown_key_rejected(self):
        errs = schemas.check("ARCHITECT", _arch(extra=1))
        self.assertTrue(any("unknown key 'extra'" in e for e in errs), errs)

    def test_wrong_type(self):
        errs = schemas.check("ARCHITECT", _arch(size=3))
        self.assertTrue(errs)

    def test_optional_key_null_is_absent(self):
        impl = {"phase": "IMPLEMENT", "workstream": None, "files": ["a"], "build_cmds": None, "unmet_ac": None}
        self.assertEqual(schemas.check("IMPLEMENT", impl), [])
        impl["build_cmds"] = "npm run build"
        self.assertTrue(schemas.check("IMPLEMENT", impl), "a wrong-typed optional key is still rejected")

    def test_retired_keys_dropped_not_rejected(self):
        o = _arch(assumptions=["x"], shared_read_only=["y"])
        self.assertEqual(schemas.check("ARCHITECT", o), [])
        self.assertNotIn("assumptions", o)
        self.assertNotIn("assumptions", schemas.render("ARCHITECT"))

    def test_design_word_cap_by_size(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        p = os.path.join(d, "design.md")
        with open(p, "w") as f:
            f.write("word " * 601)
        errs = schemas.check("ARCHITECT", _arch(size="S"), design_path=p)
        self.assertTrue(any("601 words; size S allows 600" in e for e in errs), errs)
        self.assertEqual(schemas.check("ARCHITECT", _arch(size="M"), design_path=p), [])
        self.assertEqual(schemas.check("ARCHITECT", _arch(size="S")), [], "no design_path → no length check")

    def test_bool_is_not_int(self):
        f = {"id": "R-1", "severity": "minor", "tag": "STD", "file": "a", "line": True, "desc": "d",
             "route": "implementer", "verify": "manual"}
        errs = schemas.validate(f, schemas.FINDING)
        self.assertTrue(any("expected int, got bool" in e for e in errs), errs)

    def test_render_skeleton_is_json(self):
        for ph in schemas.BY_PHASE:
            json.loads(schemas.render(ph))


class DesignFromTicket(unittest.TestCase):
    BLOCK = '```hs-design\n%s\n```'

    def t(self, body):
        return "ticket prose\n\n" + self.BLOCK % body

    def test_valid_block(self):
        out, errs = machine.design_from_ticket(self.t(json.dumps(
            {"ac": [{"id": "AC-1", "text": "x"}, {"id": "AC-2", "text": "docs"}], "owned": ["a.js"],
             "test_owned": ["t/a.test.js"], "untestable": [{"ac": "AC-2", "reason": "docs only"}]})))
        self.assertEqual(errs, [])
        self.assertEqual(out["size"], "S")
        self.assertEqual(out["workstreams"][0]["ac"], ["AC-1"], "an untestable AC is not a workstream AC")
        self.assertEqual(schemas.check("ARCHITECT", out), [])

    def test_unusable_blocks_name_the_reason(self):
        cases = {"no block here": "no ```hs-design block",
                 self.t("{not json"): "not valid JSON",
                 self.t('{"ac": [{"id": "AC-1", "text": "x"}], "owned": [], "test_owned": ["t"]}'): "owned is empty",
                 self.t('{"ac": [{"id": "AC-1", "text": "x"}], "owned": ["a"], "test_owned": []}'): "test_owned is empty",
                 self.t('{"ac": [], "owned": ["a"], "test_owned": ["t"], "files": []}'): "unknown key",
                 self.t('{"ac": [{"id": "AC-1"}], "owned": ["a"], "test_owned": ["t"]}'): "missing key 'text'"}
        for text, want in cases.items():
            out, errs = machine.design_from_ticket(text)
            self.assertIsNone(out, text)
            self.assertTrue(any(want in e for e in errs), (want, errs))

class SchemaSemantics(unittest.TestCase):
    def test_overlap_rejected(self):
        o = _arch(workstreams=[{"name": "a", "owned": ["src/**"], "depends_on": [], "ac": ["AC-1"]},
                               {"name": "b", "owned": ["src/b.js"], "depends_on": [], "ac": ["AC-2"]}])
        errs = schemas.check("ARCHITECT", o)
        self.assertTrue(any("ownership overlap" in e for e in errs), errs)

    def test_cycle_rejected(self):
        o = _arch(workstreams=[{"name": "a", "owned": ["x"], "depends_on": ["b"], "ac": ["AC-1"]},
                               {"name": "b", "owned": ["y"], "depends_on": ["a"], "ac": ["AC-2"]}])
        errs = schemas.check("ARCHITECT", o)
        self.assertTrue(any("not a DAG" in e for e in errs), errs)

    def test_uncovered_ac(self):
        o = _arch(workstreams=[{"name": "a", "owned": ["x"], "depends_on": [], "ac": ["AC-1"]}])
        errs = schemas.check("ARCHITECT", o)
        self.assertTrue(any("AC-2 is in no workstream" in e for e in errs), errs)

    def test_untestable_covers_ac(self):
        o = _arch(workstreams=[{"name": "a", "owned": ["x"], "depends_on": [], "ac": ["AC-1"]}],
                  untestable=[{"ac": "AC-2", "reason": "docs"}])
        self.assertEqual(schemas.check("ARCHITECT", o), [])

    def test_test_ac_map_must_cover(self):
        st = {"workstreams": [{"name": "a", "ac": ["AC-1", "AC-2"]}], "untestable": []}
        t = {"phase": "TEST", "workstream": None, "test_files": [], "new_tests": [], "ac_map": {"AC-1": ["t"]}}
        errs = schemas.check("TEST", t, st)
        self.assertTrue(any("AC-2 has no test" in e for e in errs), errs)
        t["untestable"] = [{"ac": "AC-2", "reason": "needs live SMS"}]
        self.assertEqual(schemas.check("TEST", t, st), [])


class Provenance(unittest.TestCase):
    CFG = ["npm run build", "npm test"]
    FLAGS = ["--run", "--filter", "--coverage"]

    def ok(self, cmd, **kw):
        good, why = provenance.classify(cmd, self.CFG, self.FLAGS, **kw)
        self.assertTrue(good, "%s -> %s" % (cmd, why))

    def bad(self, cmd, **kw):
        good, why = provenance.classify(cmd, self.CFG, self.FLAGS, **kw)
        self.assertFalse(good, "%s should be rejected" % cmd)
        return why

    def test_full_prefix_passes(self):
        self.ok("npm test")
        self.ok("npm test tests/auth")
        self.ok("npm test --coverage")

    def test_argv0_only_is_not_enough(self):
        self.bad("npm exec evil")
        self.bad("npm run evil")
        self.bad("npm install")

    def test_default_flags_accept_a_phpunit_filtered_verify(self):
        """The chief reviewer writes `phpunit --fail-on-empty-test-suite --filter X` so a filter that
        matches nothing exits 1 instead of a green 0. Rejecting that flag marks every such verify
        `untrusted`, so a fixed blocker never clears and the loop re-routes to the cap (ev-management ticket 51)."""
        from hs import config
        cfg = ["php ./vendor/bin/phpunit"]
        good, why = provenance.classify("php ./vendor/bin/phpunit --fail-on-empty-test-suite --filter testX",
                                        cfg, config.DEFAULTS["allowed_flags"], for_verify=True)
        self.assertTrue(good, why)

    def test_unknown_flag_rejected(self):
        self.assertIn("allowed_flags", self.bad("npm test --exec=x"))

    def test_launchers_rejected(self):
        for c in ("sh -c 'npm test'", "bash npm test", "env X=1 npm test", "xargs npm test",
                  "npx vitest", "pnpm dlx x", "node -e 1", "python3 -c 1", "sudo npm test"):
            self.bad(c)

    def test_shell_meta_rejected(self):
        for c in ("npm test | sh", "npm test; rm -rf /", "npm test && curl x", "npm test > out",
                  "npm test $(x)", "npm test `x`", "curl x|sh"):
            self.bad(c)

    def test_verify_bins(self):
        self.ok("grep -q foo src/a.js", for_verify=True)
        self.ok("! grep -qE 'apiKey\\s*==' src/auth.ts", for_verify=True)
        self.ok("test -f out.txt", for_verify=True)
        self.bad("grep -f patterns src", for_verify=True)
        self.bad("grep -q foo src/a.js")  # not allowed outside verify

    def test_negate_runs(self):
        code, _, _ = provenance.run_cmd("! test -f /nonexistent-hs-file", os.getcwd(), 5)
        self.assertEqual(code, 0)
        code, _, _ = provenance.run_cmd("test -f /nonexistent-hs-file", os.getcwd(), 5)
        self.assertEqual(code, 1)

    def test_timeout_kills_group(self):
        code, text = provenance.run([sys.executable, "-c", "import time; time.sleep(30)"], os.getcwd(), 1)
        self.assertEqual(code, -9)
        self.assertIn("killed after 1s", text)


class Coverage(unittest.TestCase):
    def _tmp(self, name, content):
        d = tempfile.mkdtemp()
        p = os.path.join(d, name)
        with open(p, "w") as f:
            f.write(content)
        return p

    def test_lcov(self):
        p = self._tmp("lcov.info", "SF:src/a.js\nLF:10\nLH:8\nend_of_record\nSF:src/b.js\nLF:10\nLH:10\nend_of_record\n")
        c = coverage.parse(p)
        self.assertEqual(c["status"], "ok")
        self.assertEqual(c["total"], 90.0)
        self.assertEqual(c["per_file"]["src/a.js"], 80.0)

    def test_cobertura(self):
        p = self._tmp("cov.xml", '<?xml version="1.0"?><coverage line-rate="0.75"><packages><package><classes>'
                                 '<class filename="src/a.py"><lines><line number="1" hits="1"/><line number="2" hits="0"/>'
                                 '</lines></class></classes></package></packages></coverage>')
        c = coverage.parse(p)
        self.assertEqual(c["status"], "ok")
        self.assertEqual(c["total"], 75.0)
        self.assertEqual(c["per_file"]["src/a.py"], 50.0)

    def test_istanbul(self):
        p = self._tmp("coverage-summary.json", json.dumps({"total": {"lines": {"pct": 81.5}},
                                                          "/abs/src/a.ts": {"lines": {"pct": 79.9}}}))
        c = coverage.parse(p)
        self.assertEqual(c["status"], "ok")
        self.assertEqual(c["total"], 81.5)

    def test_pytest_cov(self):
        p = self._tmp("coverage.json", json.dumps({"totals": {"percent_covered": 66.6},
                                                  "files": {"pkg/a.py": {"summary": {"percent_covered": 66.6}}}}))
        c = coverage.parse(p)
        self.assertEqual(c["status"], "ok")
        self.assertEqual(c["per_file"]["pkg/a.py"], 66.6)

    def test_missing_unsupported_unparseable(self):
        self.assertEqual(coverage.parse("/nonexistent")["status"], "missing")
        self.assertEqual(coverage.parse(self._tmp("x.txt", "hi"))["status"], "unsupported")
        self.assertEqual(coverage.parse(self._tmp("x.json", '{"foo": 1}'))["status"], "unsupported")
        self.assertEqual(coverage.parse(self._tmp("lcov.info", "garbage\n"))["status"], "unparseable")
        self.assertEqual(coverage.parse(self._tmp("c.xml", "<notcov/>"))["status"], "unparseable")
        self.assertEqual(coverage.parse(self._tmp("c.xml", "<<<"))["status"], "unparseable")

    def test_per_file_matching_abs_paths(self):
        cov = {"per_file": {"/repo/src/a.js": 50.0, "src/b.js": 60.0}}
        got = coverage.per_file_for(cov, ["src/a.js", "src/b.js", "src/c.js"], "/repo")
        self.assertEqual(got, {"src/a.js": 50.0, "src/b.js": 60.0, "src/c.js": None})


class Verdict(unittest.TestCase):
    REF = "5c56f8c26e4fe4f535adc38f012b3c36d73abea4"

    def gate(self, tests="pass", status="ok", per_file=None, rows=None, ref=None, mut=None):
        ref = ref or self.REF
        return {"tests": tests, "coverage": {"status": status, "total": 90, "per_file": per_file or {"src/a.js": 90}},
                "redgreen": {"ref": ref, "rows": rows if rows is not None else [{"test": "t/a.js", "kind": "assertion"}]},
                "mutation": {"rows": mut if mut is not None else [{"ac": "AC-1", "file": "src/a.js", "find": "x", "replace": "y", "kind": "killed"}]}}

    def test_surviving_mutant_is_a_tester_blocker(self):
        g = self.gate(mut=[{"ac": "AC-1", "file": "src/a.js", "find": "a * b", "replace": "a + b", "kind": "survived"}])
        b, _, r = machine.verdict({"findings": []}, g, 80, ["src/a.js"], ["t/a.js"], self.REF)
        self.assertEqual(([x["id"] for x in b], r), (["G-MUT"], "tester"))
        self.assertIn("'a * b'→'a + b'", b[0]["desc"])

    def test_mutation_none_and_not_applied_are_majors(self):
        _, m, _ = machine.verdict({"findings": []}, self.gate(mut=[]), 80, ["src/a.js"], ["t/a.js"], self.REF)
        self.assertIn("G-MUT-NONE", [x["id"] for x in m])
        _, m, _ = machine.verdict({"findings": []}, self.gate(mut=[{"ac": "AC-1", "file": "f", "kind": "not-applied", "evidence": "0 times"}]),
                                  80, ["src/a.js"], ["t/a.js"], self.REF)
        self.assertIn("G-MUT-NOT-APPLIED", [x["id"] for x in m])
        _, m, _ = machine.verdict({"findings": []}, self.gate(mut=[]), 80, ["src/a.js"], [], self.REF)
        self.assertNotIn("G-MUT-NONE", [x["id"] for x in m], "no new tests (refactor/docs): no mutation major")

    def test_clean_pass(self):
        b, m, r = machine.verdict({"findings": []}, self.gate(), 80, ["src/a.js"], ["t/a.js"], self.REF)
        self.assertEqual((b, r), ([], None))
        self.assertEqual(m, [])

    def test_pre_existing_failures_are_a_major_not_a_blocker(self):
        g = dict(self.gate(tests="pre-existing"), tests_pre=["✖ sub"])
        b, m, _ = machine.verdict({"findings": []}, g, 80, ["src/a.js"], ["t/a.js"], self.REF)
        self.assertEqual(b, [])
        self.assertEqual([x["id"] for x in m], ["G-TESTS-PRE"])
        self.assertIn("✖ sub", m[0]["desc"])

    def test_tests_fail_is_synthetic_blocker(self):
        b, _, r = machine.verdict({"findings": []}, self.gate(tests="fail"), 80, ["src/a.js"], ["t/a.js"], self.REF)
        self.assertEqual([x["id"] for x in b], ["G-TESTS"])
        self.assertEqual(r, "implementer")

    def test_coverage_boundary_inclusive(self):
        for v, expect_block in ((80.0, False), (79.99, True), (80.01, False)):
            b, _, _ = machine.verdict({"findings": []}, self.gate(per_file={"src/a.js": v}), 80, ["src/a.js"], ["t/a.js"], self.REF)
            self.assertEqual(bool(b), expect_block, v)

    def test_threshold_none_skips(self):
        b, _, _ = machine.verdict({"findings": []}, self.gate(per_file={"src/a.js": 1}), None, ["src/a.js"], ["t/a.js"], self.REF)
        self.assertEqual(b, [])

    def test_coverage_unsupported_is_major(self):
        b, m, _ = machine.verdict({"findings": []}, self.gate(status="unsupported"), 80, ["src/a.js"], ["t/a.js"], self.REF)
        self.assertEqual(b, [])
        self.assertIn("G-COV-UNVERIFIED", [x["id"] for x in m])

    def test_redgreen_missing_row_and_green(self):
        b, _, r = machine.verdict({"findings": []}, self.gate(rows=[]), 80, ["src/a.js"], ["t/a.js"], self.REF)
        self.assertEqual([x["id"] for x in b], ["G-RED"])
        self.assertEqual(r, "tester")
        b, _, _ = machine.verdict({"findings": []}, self.gate(rows=[{"test": "t/a.js", "kind": "green"}]), 80, ["src/a.js"], ["t/a.js"], self.REF)
        self.assertEqual([x["id"] for x in b], ["G-RED"])

    def test_redgreen_ref_mismatch(self):
        b, _, _ = machine.verdict({"findings": []}, self.gate(ref="0123456deadbeef"), 80, ["src/a.js"], ["t/a.js"], self.REF)
        self.assertTrue(any("ref mismatch" in x["desc"] for x in b))

    def test_redgreen_short_sha_tolerated(self):
        full = "5c56f8c26e4fe4f535adc38f012b3c36d73abea4"
        b, _, _ = machine.verdict({"findings": []}, self.gate(ref=full[:12]), 80, ["src/a.js"], ["t/a.js"], full)
        self.assertEqual(b, [])
        self.assertTrue(machine._same_ref(full, full[:7]))
        self.assertFalse(machine._same_ref(full, full[:6]))
        self.assertFalse(machine._same_ref(None, full))

    def test_already_proven_tests_need_no_rows(self):
        # caller filters proven tests out of new_tests; an empty need list with rows absent is not a blocker
        b, m, _ = machine.verdict({"findings": []}, self.gate(rows=[]), 80, ["src/a.js"], [], self.REF)
        self.assertEqual(b, [])
        self.assertIn("G-RED-NONE", [x["id"] for x in m])

    def test_no_new_tests_is_major_not_blocker(self):
        b, m, _ = machine.verdict({"findings": []}, self.gate(rows=[]), 80, ["src/a.js"], [], self.REF)
        self.assertEqual(b, [])
        self.assertIn("G-RED-NONE", [x["id"] for x in m])

    def test_simpl_never_blocks(self):
        f = {"id": "R-1", "severity": "blocker", "tag": "SIMPL", "file": "a", "desc": "d", "route": "implementer", "verify": "manual"}
        b, m, _ = machine.verdict({"findings": [f]}, self.gate(), 80, ["src/a.js"], ["t/a.js"], self.REF)
        self.assertEqual(b, [])
        self.assertEqual(m[0]["id"], "R-1")

    def test_route_precedence(self):
        mk = lambda tag, route: {"id": tag, "severity": "blocker", "tag": tag, "file": "a", "desc": "d", "route": route, "verify": "manual"}
        _, _, r = machine.verdict({"findings": [mk("TEST", "tester"), mk("SEC", "implementer")]}, self.gate(), 80, ["src/a.js"], ["t/a.js"], self.REF)
        self.assertEqual(r, "implementer")
        _, _, r = machine.verdict({"findings": [mk("CONFLICT", "implementer")]}, self.gate(), 80, ["src/a.js"], ["t/a.js"], self.REF)
        self.assertEqual(r, "architecter")
        _, _, r = machine.verdict({"findings": [mk("REQ", "architecter"), mk("SEC", "implementer")]}, self.gate(), 80, ["src/a.js"], ["t/a.js"], self.REF)
        self.assertEqual(r, "architecter")


class Render(unittest.TestCase):
    def test_vars_and_none(self):
        self.assertEqual(render.render_text("a {{x}} b {{y}}", {"x": "1"}), "a 1 b (none)")
        self.assertEqual(render.render_text("{{l}}", {"l": ["p", "q"]}), "- p\n- q")
        self.assertEqual(render.render_text("{{l}}", {"l": []}), "(none)")

    def test_unset_note_line_is_dropped(self):
        self.assertEqual(render.render_text("a\n{{x_note}}\nb {{y}}\n", {}), "a\nb (none)\n")
        self.assertEqual(render.render_text("a\n{{x_note}}\nb\n", {"x_note": "N"}), "a\nN\nb\n")


if __name__ == "__main__":
    unittest.main()
