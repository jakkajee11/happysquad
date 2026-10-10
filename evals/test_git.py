"""Unit tests for the hs modules that touch git or the filesystem — stdlib only, no model calls.

Each test builds a throwaway git repo under tempfile.mkdtemp() and cleans up via addCleanup.
Redgreen tests copy evals/fixtures/toy-repo/ into the temp repo (node >= 20 required).

Run: python3 -m unittest discover -s evals -p 'test_git.py' -v
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from hs import gates, gitutil, redgreen, state  # noqa: E402

TOY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "toy-repo")


def _git(root, *args, check=True):
    p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), p.stderr))
    return p.stdout


def _commit_all(root, msg):
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", msg)


class TmpRepoCase(unittest.TestCase):
    """One commit (tracked.txt) in a fresh repo under self.root."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hs-git-test-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        _git(self.root, "init", "-q")
        with open(os.path.join(self.root, "tracked.txt"), "w") as f:
            f.write("v1\n")
        _commit_all(self.root, "init")


class AtomicWrite(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="hs-atomic-")
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)

    def _tmp_leftovers(self):
        return [n for n in os.listdir(self.d) if n.startswith(".tmp-")]

    def test_replaces_atomically_no_tmp_leftover(self):
        p = os.path.join(self.d, "f.json")
        state.atomic_write(p, "hello\n")
        with open(p) as f:
            self.assertEqual(f.read(), "hello\n")
        state.atomic_write(p, "world\n")
        with open(p) as f:
            self.assertEqual(f.read(), "world\n")
        self.assertEqual(self._tmp_leftovers(), [])

    def test_exception_mid_write_leaves_no_partial_file_or_tmp(self):
        p = os.path.join(self.d, "f.json")
        with self.assertRaises(TypeError):
            state.atomic_write(p, None)  # f.write(None) raises TypeError inside the `with`
        self.assertFalse(os.path.exists(p))
        self.assertEqual(self._tmp_leftovers(), [])


class Commit(unittest.TestCase):
    def setUp(self):
        self.rdir = tempfile.mkdtemp(prefix="hs-run-")
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        os.chmod(self.rdir, 0o755)
        shutil.rmtree(self.rdir, ignore_errors=True)

    def test_event_appended_then_state_saved(self):
        st = {"phase": "IMPLEMENT"}
        state.commit(self.rdir, st, "dispatch", workstream="backend")
        events = state.read_events(self.rdir)
        self.assertEqual([e["event"] for e in events], ["dispatch"])
        self.assertEqual(events[0]["workstream"], "backend")
        saved = state.load_state(self.rdir)
        self.assertEqual(saved["phase"], "IMPLEMENT")
        self.assertIn("updated_at", saved)

    def test_event_survives_state_save_failure(self):
        state.append_event(self.rdir, "dispatch")
        os.chmod(self.rdir, 0o555)  # read-only dir: save_state's mkstemp must fail
        try:
            with self.assertRaises(OSError):
                state.save_state(self.rdir, {"x": 1})
        finally:
            os.chmod(self.rdir, 0o755)
        self.assertEqual([e["event"] for e in state.read_events(self.rdir)], ["dispatch"])


class Locked(unittest.TestCase):
    # second process: non-blocking flock on the same .lock path, exit 42 if it would block
    PROBE = (
        "import fcntl, sys\n"
        "f = open(sys.argv[1], 'a+')\n"
        "try:\n"
        "    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "except BlockingIOError:\n"
        "    sys.exit(42)\n"
        "sys.exit(0)\n"
    )

    def setUp(self):
        self.rdir = tempfile.mkdtemp(prefix="hs-lock-")
        self.addCleanup(shutil.rmtree, self.rdir, ignore_errors=True)

    def _probe(self):
        lock_path = os.path.join(self.rdir, ".lock")
        return subprocess.run([sys.executable, "-c", self.PROBE, lock_path]).returncode

    def test_second_process_blocked_then_free_after_release(self):
        with state.locked(self.rdir):
            self.assertEqual(self._probe(), 42, "second process should fail to acquire the held lock")
        self.assertEqual(self._probe(), 0, "lock should be free after release")


class Now(unittest.TestCase):
    def test_honours_hs_now(self):
        old = os.environ.get("HS_NOW")
        os.environ["HS_NOW"] = "2020-01-01T00:00:00Z"
        try:
            self.assertEqual(state.now(), "2020-01-01T00:00:00Z")
        finally:
            if old is None:
                os.environ.pop("HS_NOW", None)
            else:
                os.environ["HS_NOW"] = old


class Snapshot(TmpRepoCase):
    def test_dirty_untracked_ignored_and_index_untouched(self):
        root = self.root
        with open(os.path.join(root, ".gitignore"), "w") as f:
            f.write("ignored.txt\n")
        _commit_all(root, "gitignore")

        with open(os.path.join(root, "tracked.txt"), "w") as f:
            f.write("v2\n")  # dirty, unstaged
        with open(os.path.join(root, "untracked.txt"), "w") as f:
            f.write("new\n")
        with open(os.path.join(root, "ignored.txt"), "w") as f:
            f.write("nope\n")
        os.makedirs(os.path.join(root, ".happysquad"))
        with open(os.path.join(root, ".happysquad", "x.json"), "w") as f:
            f.write("{}")
        os.makedirs(os.path.join(root, "knowledge"))
        with open(os.path.join(root, "knowledge", "wiki.md"), "w") as f:
            f.write("# wiki")

        before = _git(root, "status", "--porcelain")
        sha = gitutil.snapshot(root, "testrun/base")
        after = _git(root, "status", "--porcelain")
        self.assertEqual(before, after, "real index/worktree must be untouched by snapshot")

        names = _git(root, "ls-tree", "-r", "--name-only", sha).splitlines()
        self.assertIn("tracked.txt", names)
        self.assertIn("untracked.txt", names)
        self.assertNotIn("ignored.txt", names)
        self.assertFalse(any(n.startswith(".happysquad/") for n in names))
        self.assertFalse(any(n.startswith("knowledge/") for n in names))
        self.assertEqual(_git(root, "show", "%s:tracked.txt" % sha), "v2\n")

        self.assertEqual(_git(root, "rev-parse", "refs/happysquad/testrun/base").strip(), sha)
        gitutil.delete_refs(root, "testrun")
        self.assertEqual(_git(root, "rev-parse", "--verify", "refs/happysquad/testrun/base", check=False), "")


class SnapshotNoCommits(unittest.TestCase):
    def test_no_commits_returns_none(self):
        root = tempfile.mkdtemp(prefix="hs-nocommit-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        _git(root, "init", "-q")
        self.assertIsNone(gitutil.snapshot(root, "x/base"))


class ChangedFiles(TmpRepoCase):
    def test_tracked_and_untracked_excluding_happysquad_and_knowledge(self):
        root = self.root
        with open(os.path.join(root, "tracked.txt"), "w") as f:
            f.write("v2\n")
        with open(os.path.join(root, "untracked.txt"), "w") as f:
            f.write("new\n")
        os.makedirs(os.path.join(root, ".happysquad"))
        with open(os.path.join(root, ".happysquad", "x.json"), "w") as f:
            f.write("{}")
        os.makedirs(os.path.join(root, "knowledge"))
        with open(os.path.join(root, "knowledge", "wiki.md"), "w") as f:
            f.write("# wiki")

        self.assertEqual(gitutil.changed_files(root, "HEAD"), ["tracked.txt", "untracked.txt"])
        self.assertEqual(gitutil.changed_files(root, None), ["untracked.txt"])

    def test_untracked_file_present_at_base_snapshot_is_not_a_change(self):
        root = self.root
        with open(os.path.join(root, "scratch.txt"), "w") as f:
            f.write("user's own untracked file\n")
        base = gitutil.snapshot(root, "t/base")
        self.assertEqual(gitutil.changed_files(root, base), [])
        with open(os.path.join(root, "new_by_run.txt"), "w") as f:
            f.write("x\n")
        with open(os.path.join(root, "scratch.txt"), "a") as f:
            f.write("edited\n")
        self.assertEqual(gitutil.changed_files(root, base), ["new_by_run.txt", "scratch.txt"])
        os.unlink(os.path.join(root, "scratch.txt"))
        self.assertEqual(gitutil.changed_files(root, base), ["new_by_run.txt", "scratch.txt"])  # deletion is a change
        self.assertEqual(_git(root, "status", "--porcelain"), "?? new_by_run.txt\n", "real index untouched")


class Prune(TmpRepoCase):
    def test_removes_stale_tmp_dir(self):
        tmp = gitutil.tmp_dir(self.root)
        stale = os.path.join(tmp, "stale-leftover")
        os.makedirs(stale)
        with open(os.path.join(stale, "f"), "w") as f:
            f.write("x")
        gitutil.prune(self.root)
        self.assertFalse(os.path.exists(stale))


@unittest.skipUnless(shutil.which("node"), "node not installed")
class RedGreen(unittest.TestCase):
    CMD = "npm test -- {file}"
    # toy-repo's npm test writes to coverage/lcov.info, and coverage/ is gitignored so a fresh
    # worktree checkout never has it; copy materializes the dir, same as a real redgreen_cmd config would.
    COPY = ("coverage/.gitkeep",)

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hs-toy-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for name in os.listdir(TOY):
            src, dst = os.path.join(TOY, name), os.path.join(self.root, name)
            (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, dst)
        _git(self.root, "init", "-q")
        _commit_all(self.root, "init")
        self.ref = _git(self.root, "rev-parse", "HEAD").strip()

        old = os.environ.get("HS_TOY_FAST")
        os.environ["HS_TOY_FAST"] = "1"
        self.addCleanup(lambda: os.environ.pop("HS_TOY_FAST", None) if old is None
                         else os.environ.update(HS_TOY_FAST=old))

    def _write(self, rel, content):
        path = os.path.join(self.root, rel)
        with open(path, "w") as f:
            f.write(content)

    def test_compile_kind(self):
        self._write("test/new_compile.test.js",
                     'import { test } from "node:test";\n'
                     'import { mul } from "../src/calc.js";\n'
                     'test("uses mul", () => { mul(2, 2); });\n')
        res = redgreen.prove(self.root, self.ref, ["test/new_compile.test.js"], self.CMD, copy=self.COPY)
        self.assertEqual(res["rows"][0]["kind"], "compile")

    def test_assertion_kind(self):
        self._write("test/new_assert.test.js",
                     'import { test } from "node:test";\n'
                     'import assert from "node:assert/strict";\n'
                     'import { add } from "../src/calc.js";\n'
                     'test("bad assert", () => { assert.equal(add(2, 2), 5); });\n')
        res = redgreen.prove(self.root, self.ref, ["test/new_assert.test.js"], self.CMD, copy=self.COPY)
        self.assertEqual(res["rows"][0]["kind"], "assertion")

    def test_green_kind_and_cleanup(self):
        res = redgreen.prove(self.root, self.ref, ["test/calc.test.js"], self.CMD, copy=self.COPY)
        self.assertEqual(res["rows"][0]["kind"], "green")
        self.assertEqual(len(_git(self.root, "worktree", "list").splitlines()), 1)
        self.assertEqual(os.listdir(gitutil.tmp_dir(self.root)), [])

    def test_ref_none_is_not_runnable(self):
        res = redgreen.prove(self.root, None, ["test/calc.test.js", "test/x.test.js"], self.CMD)
        self.assertTrue(all(r["kind"] == "not-runnable" for r in res["rows"]))

    def test_bogus_ref_is_not_runnable(self):
        res = redgreen.prove(self.root, "not-a-real-ref", ["test/calc.test.js"], self.CMD)
        self.assertEqual(res["rows"][0]["kind"], "not-runnable")
        self.assertIn("worktree add failed", res["rows"][0]["evidence"])

@unittest.skipUnless(shutil.which("node"), "node not installed")
class Mutate(unittest.TestCase):
    """redgreen.mutate: killed / survived / not-applied, each mutant on its own copy, live tree untouched."""
    CMD = "node --test {file}"

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hs-mut-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        os.makedirs(os.path.join(self.root, "src")); os.makedirs(os.path.join(self.root, "test"))
        with open(os.path.join(self.root, "src", "m.js"), "w") as f:
            f.write("export function mul(a, b) {\n  return a * b;\n}\n")
        with open(os.path.join(self.root, "test", "strong.test.js"), "w") as f:
            f.write('import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
                    'import { mul } from "../src/m.js";\ntest("m", () => { assert.equal(mul(3, 4), 12); });\n')
        with open(os.path.join(self.root, "test", "weak.test.js"), "w") as f:
            f.write('import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
                    'import { mul } from "../src/m.js";\ntest("m", () => { assert.equal(typeof mul(3, 4), "number"); });\n')
        with open(os.path.join(self.root, "package.json"), "w") as f:
            f.write('{"type": "module"}\n')
        _git(self.root, "init", "-q")
        _commit_all(self.root, "init")
        self.ref = _git(self.root, "rev-parse", "HEAD").strip()

    def test_kinds(self):
        bug = {"ac": "AC-1", "file": "src/m.js", "find": "return a * b;", "replace": "return a + b;"}
        res = redgreen.mutate(self.root, self.ref, [dict(bug, tests=["test/strong.test.js"]),
                                                    dict(bug, tests=["test/weak.test.js"]),
                                                    dict(bug, find="not in file", tests=["test/strong.test.js"]),
                                                    dict(bug, tests=[])], self.CMD)
        self.assertEqual([r["kind"] for r in res["rows"]], ["killed", "survived", "not-applied", "not-applied"])
        with open(os.path.join(self.root, "src", "m.js")) as f:
            self.assertIn("a * b", f.read(), "live tree never mutated")
        self.assertEqual(len(_git(self.root, "worktree", "list").splitlines()), 1, "every mutation worktree removed")

class CoverageForGate(TmpRepoCase):
    """Docs, deleted files and deletion-only edits have nothing to cover: never G-COV-UNVERIFIED."""

    def test_non_code_deleted_and_deletion_only_files_are_skipped(self):
        root = self.root
        for rel, body in (("src/a.js", "x\ny\nz\n"), ("src/gone.js", "g\n"), ("src/trim.js", "1\n2\n3\n")):
            os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
            with open(os.path.join(root, rel), "w") as f:
                f.write(body)
        _commit_all(root, "code")
        base = _git(root, "rev-parse", "HEAD").strip()
        with open(os.path.join(root, "src/a.js"), "a") as f:
            f.write("w\n")
        with open(os.path.join(root, "src/trim.js"), "w") as f:
            f.write("1\n2\n")
        with open(os.path.join(root, "src/untested.js"), "w") as f:
            f.write("u\n")
        os.unlink(os.path.join(root, "src/gone.js"))
        with open(os.path.join(root, "NOTES.md"), "w") as f:
            f.write("# notes\n")
        cov = {"status": "ok", "total": 50.0, "per_file": {"src/a.js": 100.0}, "lines": {"src/a.js": {4: 1}}}
        files = ["NOTES.md", "src/a.js", "src/gone.js", "src/trim.js", "src/untested.js"]
        pf, unv = gates.coverage_for_gate(root, cov, files, base, "delta")
        self.assertEqual(pf, {"src/a.js": 100.0, "src/untested.js": None})
        self.assertEqual(unv, ["src/untested.js"], "a code file with no per-line data is still unverified")
        pf, unv = gates.coverage_for_gate(root, cov, files, base, "file")
        self.assertEqual(sorted(pf), ["src/a.js", "src/trim.js", "src/untested.js"])

class SuiteBaseline(TmpRepoCase):
    """G-TESTS vs base: a failure already present at base_ref is `pre-existing`, a new one stays `fail`."""
    CFG = {"test_cmd": "npm test", "gate_timeout": 120, "coverage_report": "coverage/lcov.info"}

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hs-bl-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        shutil.copytree(TOY, self.root, dirs_exist_ok=True)
        os.makedirs(os.path.join(self.root, "coverage"), exist_ok=True)
        self._sed("src/calc.js", "return a - b;", "return a + b;")  # pre-existing: sub() is broken at base
        _git(self.root, "init", "-q")
        _commit_all(self.root, "init")
        self.base = _git(self.root, "rev-parse", "HEAD").strip()
        self.rdir = tempfile.mkdtemp(prefix="hs-bl-run-")
        self.addCleanup(shutil.rmtree, self.rdir, ignore_errors=True)
        # gates.GATE_ENV is a snapshot taken at import; the toy's slowOnce() must see HS_TOY_FAST there
        old = gates.GATE_ENV.get("HS_TOY_FAST")
        gates.GATE_ENV["HS_TOY_FAST"] = "1"
        self.addCleanup(lambda: gates.GATE_ENV.pop("HS_TOY_FAST", None) if old is None else gates.GATE_ENV.update(HS_TOY_FAST=old))

    def _sed(self, rel, a, b):
        p = os.path.join(self.root, rel)
        with open(p) as f:
            s = f.read()
        self.assertIn(a, s)
        with open(p, "w") as f:
            f.write(s.replace(a, b))

    def _gate(self):
        pd = os.path.join(self.rdir, "TEST-i1")
        os.makedirs(os.path.join(pd, "logs"), exist_ok=True)
        return gates.gate_test(self.root, self.rdir, pd, {}, self.CFG, [], self.base, "delta")

    def test_only_base_failures_is_pre_existing_and_cached(self):
        with open(os.path.join(self.root, "src", "calc.js"), "a") as f:
            f.write("\nexport function mul(a, b) {\n  return a * b;\n}\n")
        g = self._gate()
        self.assertEqual(g["tests"], "pre-existing", g.get("tests_new"))
        self.assertTrue(g["ok"])
        self.assertTrue(any("sub" in l for l in g["tests_pre"]), g["tests_pre"])
        bl = state.read_json(os.path.join(self.rdir, "baseline-tests.json"))
        self.assertEqual((bl["ref"], bl["exit"] != 0), (self.base, True))
        self.assertEqual(len(_git(self.root, "worktree", "list").splitlines()), 1, "baseline worktree removed")

    def test_new_failure_alongside_base_failure_is_fail(self):
        self._sed("src/calc.js", "return a + b;\n}\n\nexport function sub", "return a - b;\n}\n\nexport function sub")
        g = self._gate()
        self.assertEqual(g["tests"], "fail")
        self.assertTrue(any("add" in l for l in g["tests_new"]), g["tests_new"])

    def test_green_base_keeps_fail(self):
        self._sed("src/calc.js", "return a + b;\n}\n\nexport function sub", "return a - b;\n}\n\nexport function sub")
        self._sed("src/calc.js", "export function sub(a, b) {\n  return a + b;", "export function sub(a, b) {\n  return a - b;")
        _commit_all(self.root, "fix sub, break add")
        self.base = _git(self.root, "rev-parse", "HEAD~1").strip()  # base still has the broken sub
        self._sed("src/calc.js", "export function sub(a, b) {\n  return a - b;", "export function sub(a, b) {\n  return a + b;")
        self.assertEqual(self._gate()["tests"], "fail")  # head fails add+sub, base only sub → add is new

    def test_failure_lines_normalise_durations(self):
        a = redgreen.failure_lines("✖ sub (0.709084ms)\nok 1 - add\nnot ok 3 - sub\n✖ failing tests:\n")
        b = redgreen.failure_lines("✖ sub (12.1ms)\nnot ok 7 - sub\n")
        self.assertEqual(a, b)
        self.assertEqual(redgreen.failure_lines("all good\n"), set())


@unittest.skipUnless(shutil.which("php"), "php not installed")
class RedGreenComposerVendor(unittest.TestCase):
    """vendor/ symlinked into the old-ref worktree resolves Composer's project root through the
    symlink target — `App\\` autoloads the *live* tree's app/, the old ref never runs, and a test that
    pins new behaviour comes back green (ev-management ticket 47, 2026-10-05)."""

    AUTOLOAD = (
        "<?php\n"
        "// Composer's shape: project root = dirname(dirname(__DIR__)) of vendor/composer\n"
        "spl_autoload_register(function ($c) {\n"
        "    $base = dirname(dirname(__DIR__));\n"
        "    if (strpos($c, 'App\\\\') === 0) { require $base . '/app/' . substr($c, 4) . '.php'; }\n"
        "});\n"
    )

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hs-composer-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for d in ("app", "tests", "vendor/composer"):
            os.makedirs(os.path.join(self.root, d))
        self._write(".gitignore", "vendor/\n")
        self._write("vendor/composer/autoload_real.php", self.AUTOLOAD)
        self._write("vendor/autoload.php", "<?php require __DIR__ . '/composer/autoload_real.php';\n")
        self._write("app/Calc.php", "<?php namespace App; class Calc { static function v() { return 1; } }\n")
        _git(self.root, "init", "-q")
        _commit_all(self.root, "init")
        self.ref = _git(self.root, "rev-parse", "HEAD").strip()
        # the change under test: live tree now returns 2, the test pins 2 — must be red at self.ref
        self._write("app/Calc.php", "<?php namespace App; class Calc { static function v() { return 2; } }\n")
        self._write("tests/calc_test.php",
                    "<?php require __DIR__ . '/../vendor/autoload.php';\n"
                    "exit(\\App\\Calc::v() === 2 ? 0 : 1);\n")

    def _write(self, rel, content):
        with open(os.path.join(self.root, rel), "w") as f:
            f.write(content)

    def test_old_ref_runs_the_old_code_not_the_live_tree(self):
        res = redgreen.prove(self.root, self.ref, ["tests/calc_test.php"], "php {file}")
        self.assertEqual(res["rows"][0]["kind"], "assertion",
                         "vendor/ must not resolve App\\ to the live tree: " + res["rows"][0].get("evidence", ""))

    def test_live_vendor_is_untouched_and_worktree_removed(self):
        redgreen.prove(self.root, self.ref, ["tests/calc_test.php"], "php {file}")
        self.assertTrue(os.path.isfile(os.path.join(self.root, "vendor/composer/autoload_real.php")))
        self.assertEqual(len(_git(self.root, "worktree", "list").splitlines()), 1)

class Classify(unittest.TestCase):
    def test_exit0_is_green(self):
        self.assertEqual(redgreen.classify(0, "anything"), "green")

    def test_syntax_error_is_compile(self):
        self.assertEqual(redgreen.classify(1, "foo\nSyntaxError: bad\n"), "compile")

    def test_plain_failure_is_assertion(self):
        self.assertEqual(redgreen.classify(1, "AssertionError: 1 != 2\n"), "assertion")


class SnapshotIgnoredHappysquad(unittest.TestCase):
    """A repo whose root .gitignore lists .happysquad/ (this repo does) must still snapshot (seen in bench B5/B3)."""

    def test_snapshot_with_ignored_happysquad_dir(self):
        import subprocess, tempfile, shutil, os, sys
        w = tempfile.mkdtemp(prefix="hs-gi-")
        try:
            open(os.path.join(w, "a.txt"), "w").write("a\n")
            open(os.path.join(w, ".gitignore"), "w").write(".happysquad/\n")
            subprocess.run(["git", "init", "-q"], cwd=w, check=True)
            subprocess.run(["git", "add", "-A"], cwd=w, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], cwd=w, check=True)
            os.makedirs(os.path.join(w, ".happysquad", "runs"))
            open(os.path.join(w, ".happysquad", "config.json"), "w").write("{}")
            open(os.path.join(w, "b.txt"), "w").write("b\n")
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
            from hs import gitutil
            sha = gitutil.snapshot(w, "t/base")
            self.assertTrue(sha)
            tree = subprocess.run(["git", "ls-tree", "-r", "--name-only", sha], cwd=w, capture_output=True, text=True).stdout.split()
            self.assertIn("b.txt", tree)
            self.assertFalse(any(t.startswith(".happysquad") for t in tree))
        finally:
            shutil.rmtree(w, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
