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

from hs import gitutil, redgreen, state  # noqa: E402

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


class Classify(unittest.TestCase):
    def test_exit0_is_green(self):
        self.assertEqual(redgreen.classify(0, "anything"), "green")

    def test_syntax_error_is_compile(self):
        self.assertEqual(redgreen.classify(1, "foo\nSyntaxError: bad\n"), "compile")

    def test_plain_failure_is_assertion(self):
        self.assertEqual(redgreen.classify(1, "AssertionError: 1 != 2\n"), "assertion")


if __name__ == "__main__":
    unittest.main()
