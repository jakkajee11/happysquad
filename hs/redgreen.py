"""Red→green proof (spec §7.3): run each new test file inside a throwaway worktree at `ref`.

kind: assertion | compile | green | not-runnable

Also the G-TESTS baseline: the full suite at the run's base ref, for telling pre-existing failures apart.
"""
import contextlib
import os
import re
import shutil
import subprocess

from . import gitutil, provenance

COMPILE_RE = re.compile(
    r"Cannot find module|does not provide an export|ModuleNotFoundError|cannot find symbol|error TS\d+|"
    r"SyntaxError|ImportError|undefined reference|package .* is not in|ERR_MODULE_NOT_FOUND")
DEFAULT_LINKS = ("node_modules", "vendor", ".venv", ".env.testing")
# Copied, not symlinked: Composer's autoloader computes the project root as dirname(vendor/) from
# __DIR__, which PHP resolves through a symlink to the *live* tree — `App\\` then loads the changed
# code and the old ref never runs (every PHP test reads green). A real copy keeps the root inside wt.
COPY_DIRS = ("vendor",)


def classify(code, text):
    if code == 0:
        return "green"
    if COMPILE_RE.search(text or ""):
        return "compile"
    return "assertion"


def _tail(text, n=5):
    lines = [l for l in (text or "").splitlines() if l.strip()]
    return "\n".join(lines[-n:])


@contextlib.contextmanager
def _worktree_at(root, ref, name, copy=(), link=(), mkdirs=()):
    """Throwaway worktree at `ref` with `copy` files from the live tree and deps linked in.

    Yields (path, None), or (None, error) when the worktree can't be created. Always cleaned up.
    """
    wt = os.path.join(gitutil.tmp_dir(root), "%s-%d" % (name, os.getpid()))
    try:
        p = subprocess.run(["git", "worktree", "add", "--detach", wt, ref], cwd=root, capture_output=True, text=True)
        if p.returncode != 0:
            yield None, "worktree add failed: " + p.stderr.strip()[:300]
            return
        for rel in copy:
            src = os.path.join(root, rel)
            if os.path.isfile(src):
                dst = os.path.join(wt, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy(src, dst)
        for rel in (link or DEFAULT_LINKS):
            src = os.path.join(root, rel)
            dst = os.path.join(wt, rel)
            if os.path.exists(src) and not os.path.lexists(dst):
                if rel in COPY_DIRS and os.path.isdir(src):
                    shutil.copytree(src, dst, symlinks=True)
                else:
                    os.symlink(os.path.abspath(src), dst)
        for rel in mkdirs:
            if rel:
                os.makedirs(os.path.join(wt, rel), exist_ok=True)
        yield wt, None
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=root, capture_output=True)
        shutil.rmtree(wt, ignore_errors=True)

def prove(root, ref, tests, cmd_tpl, copy=(), link=(), timeout=600, mkdirs=()):
    """`mkdirs`: repo-relative dirs the runner expects to exist (e.g. a gitignored coverage/ output dir)."""
    rows = []
    if not ref:
        return {"ref": None, "rows": [{"test": t, "kind": "not-runnable", "evidence": "no ref (repo had no commits)"} for t in tests]}
    with _worktree_at(root, ref, "red", list(tests) + list(copy), link, mkdirs) as (wt, err):
        if err:
            return {"ref": ref, "rows": [{"test": t, "kind": "not-runnable", "evidence": err} for t in tests]}
        for t in tests:
            argv = provenance.split(cmd_tpl.replace("{file}", t))
            if not argv:
                rows.append({"test": t, "kind": "not-runnable", "evidence": "bad command template"})
                continue
            code, text = provenance.run(argv, wt, timeout)
            rows.append({"test": t, "kind": classify(code, text), "exit": code, "evidence": _tail(text)})
    return {"ref": ref, "rows": rows}

# One line per failing test, across common runners (node:test ✖, jest ✕, vitest ×, TAP, pytest,
# go, phpunit/mocha "1) "). ponytail: heuristic — a runner whose failure lines match none of these
# yields no failures, which the caller reads as "unknown" and keeps the blocker; add its marker here.
_FAIL_LINE = re.compile(r"^\s*(✖|✕|✗|×|not ok\b|FAIL(ED)?\b|--- FAIL:|ERROR\b|\d+\) )(?!\s*failing tests:)")
# durations, addresses and ordinals drift between runs; strip them before comparing
_NOISE = re.compile(r"\(\d+(\.\d+)?\s*m?s\)|\b\d+(\.\d+)?\s*m?s\b|0x[0-9a-f]+|^\s*\d+\)\s*|(?<=not ok)\s+\d+", re.I)

def failure_lines(text):
    """Normalised set of failing-test lines in a test runner's output."""
    out = set()
    for l in (text or "").splitlines():
        if _FAIL_LINE.match(l):
            k = _NOISE.sub("", l).strip()
            if k:
                out.add(k)
    return out

def baseline(root, ref, test_cmd, timeout=600, mkdirs=(), env=None):
    """Run the full suite at `ref` (G-TESTS baseline). Returns {ref, exit, failures, evidence}.

    exit is None when the suite could not run there at all.
    """
    if not ref:
        return {"ref": None, "exit": None, "failures": [], "evidence": "no ref"}
    with _worktree_at(root, ref, "base", mkdirs=mkdirs) as (wt, err):
        if err:
            return {"ref": ref, "exit": None, "failures": [], "evidence": err}
        code, text, _ = provenance.run_cmd(test_cmd, wt, timeout, env=env)
        text = text.replace(wt, root)  # absolute paths in failure lines must match the live tree's
        return {"ref": ref, "exit": code, "failures": sorted(failure_lines(text)), "evidence": _tail(text)}
