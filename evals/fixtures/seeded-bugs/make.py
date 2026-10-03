#!/usr/bin/env python3
"""Build the seeded-bugs fixture (spec §18.2).

Copies the current hs/ package into evals/fixtures/seeded-bugs/hs/, plants three
known defects by exact string replacement (fails loudly if an anchor has drifted),
writes diff.patch, and prints the planted file:line table. Idempotent: re-running
rebuilds hs/ fresh from the current main hs/ every time.

Usage: python3 evals/fixtures/seeded-bugs/make.py
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # .../happysquad
SRC_HS = os.path.join(ROOT, "hs")
DST_HS = os.path.join(HERE, "hs")
DIFF_PATCH = os.path.join(HERE, "diff.patch")

BUGS = []  # filled in by plant(), used for the printed table


def plant(relpath, bug_id, desc, old, new, marker):
    """Apply one exact-string replacement. `marker` is the single changed line used
    to report file:line (old/new share context lines, so the replaced block's start
    is not necessarily the defect line itself)."""
    path = os.path.join(DST_HS, relpath)
    text = open(path, encoding="utf-8").read()
    n = text.count(old)
    if n != 1:
        sys.exit(
            "[make.py] %s: expected exactly 1 occurrence of anchor in hs/%s, found %d.\n"
            "hs/ engine has drifted since this fixture was written — update the anchor." % (bug_id, relpath, n)
        )
    text = text.replace(old, new, 1)
    open(path, "w", encoding="utf-8").write(text)
    line = text[:text.index(marker)].count("\n") + 1
    BUGS.append((bug_id, "hs/%s" % relpath, line, desc))


def clean_pycache(root):
    for dirpath, dirnames, _ in os.walk(root):
        if "__pycache__" in dirnames:
            shutil.rmtree(os.path.join(dirpath, "__pycache__"))
            dirnames.remove("__pycache__")


def main():
    if os.path.isdir(DST_HS):
        shutil.rmtree(DST_HS)
    shutil.copytree(SRC_HS, DST_HS, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    clean_pycache(DST_HS)  # belt-and-suspenders: never commit a copied __pycache__

    plant(
        "machine.py", "B-A", "_same_ref() matches any two non-empty strings (no prefix/length check)",
        old='    a, b = str(a), str(b)\n'
            '    return (a.startswith(b) or b.startswith(a)) and min(len(a), len(b)) >= 7\n',
        new='    a, b = str(a), str(b)\n'
            '    return True\n',
        marker='    return True\n',
    )

    plant(
        "gates.py", "B-B", "gate_test ignores agent-supplied test_cmds exit codes",
        old='    tests_ok, results = _run_all(root, phase_dir, cmds, cfg, "test", stop_on_fail=False)\n'
            '    report = out.get("coverage_report") or cfg.get("coverage_report")\n',
        new='    tests_ok, results = _run_all(root, phase_dir, cmds, cfg, "test", stop_on_fail=False)\n'
            '    tests_ok = all(r["exit"] == 0 for r in results if r["source"] == "config")\n'
            '    report = out.get("coverage_report") or cfg.get("coverage_report")\n',
        marker='    tests_ok = all(r["exit"] == 0 for r in results if r["source"] == "config")\n',
    )

    plant(
        "gitutil.py", "B-C", "snapshot() points GIT_INDEX_FILE at the real index, not a temp copy",
        old='    tmp = tmp_dir(root)\n'
            '    idx = os.path.join(tmp, "index-%d" % os.getpid())\n'
            '    real = os.path.join(common_dir(root), "index")\n'
            '    try:\n'
            '        if os.path.isfile(real):\n'
            '            shutil.copy(real, idx)\n'
            '        env = dict(os.environ, GIT_INDEX_FILE=idx)\n',
        new='    tmp = tmp_dir(root)\n'
            '    real = os.path.join(common_dir(root), "index")\n'
            '    idx = real\n'
            '    try:\n'
            '        env = dict(os.environ, GIT_INDEX_FILE=idx)\n',
        marker='    idx = real\n',
    )

    p = subprocess.run(
        ["git", "diff", "--no-index", "--", "hs/", "evals/fixtures/seeded-bugs/hs/"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if p.returncode not in (0, 1):
        sys.exit("[make.py] git diff --no-index failed: %s" % p.stderr)
    open(DIFF_PATCH, "w", encoding="utf-8").write(p.stdout)

    print("planted bugs:")
    for bug_id, path, line, desc in BUGS:
        print("  %-4s %s:%d  %s" % (bug_id, path, line, desc))
    print("diff written to %s" % os.path.relpath(DIFF_PATCH, ROOT))


if __name__ == "__main__":
    main()
