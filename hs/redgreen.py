"""Red→green proof (spec §7.3): run each new test file inside a throwaway worktree at `ref`.

kind: assertion | compile | green | not-runnable
"""
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


def prove(root, ref, tests, cmd_tpl, copy=(), link=(), timeout=600, mkdirs=()):
    """`mkdirs`: repo-relative dirs the runner expects to exist (e.g. a gitignored coverage/ output dir)."""
    rows = []
    if not ref:
        return {"ref": None, "rows": [{"test": t, "kind": "not-runnable", "evidence": "no ref (repo had no commits)"} for t in tests]}
    wt = os.path.join(gitutil.tmp_dir(root), "red-%d" % os.getpid())
    try:
        p = subprocess.run(["git", "worktree", "add", "--detach", wt, ref], cwd=root, capture_output=True, text=True)
        if p.returncode != 0:
            return {"ref": ref, "rows": [{"test": t, "kind": "not-runnable", "evidence": "worktree add failed: " + p.stderr.strip()[:300]} for t in tests]}
        for rel in list(tests) + list(copy):
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
        for t in tests:
            argv = provenance.split(cmd_tpl.replace("{file}", t))
            if not argv:
                rows.append({"test": t, "kind": "not-runnable", "evidence": "bad command template"})
                continue
            code, text = provenance.run(argv, wt, timeout)
            rows.append({"test": t, "kind": classify(code, text), "exit": code, "evidence": _tail(text)})
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=root, capture_output=True)
        shutil.rmtree(wt, ignore_errors=True)
    return {"ref": ref, "rows": rows}
