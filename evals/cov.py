#!/usr/bin/env python3
"""Stdlib line coverage for the hs package: runs the unittest suite under `trace` and writes lcov.

Usage: python3 evals/cov.py [-p PATTERN] [--out coverage/lcov.info]
Exit code = unittest result (0 pass, 1 fail). Coverage is best-effort line coverage of hs/*.py.
"""
import argparse
import os
import sys
import trace
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PKG = os.path.realpath(os.path.join(ROOT, "hs"))


def executable_lines(path):
    """Lines that can execute, per the compiled code object (same notion `trace` uses)."""
    with open(path) as f:
        code = compile(f.read(), path, "exec")
    lines = set()
    stack = [code]
    while stack:
        c = stack.pop()
        # co_lines() is the public API (3.10+); None line numbers mark artificial instructions
        for _, _, ln in c.co_lines():
            if ln is not None:
                lines.add(ln)
        for const in c.co_consts:
            if hasattr(const, "co_code"):
                stack.append(const)
    if not lines:
        # fallback: every line that is not blank/comment/docstring-ish
        with open(path) as f:
            for i, l in enumerate(f, 1):
                s = l.strip()
                if s and not s.startswith("#"):
                    lines.add(i)
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--pattern", default="test_*.py")
    ap.add_argument("--out", default="coverage/lcov.info")
    args = ap.parse_args()

    sys.path.insert(0, ROOT)
    tracer = trace.Trace(count=True, trace=False, ignoredirs=[sys.prefix, sys.exec_prefix])
    suite = unittest.defaultTestLoader.discover(HERE, pattern=args.pattern)
    result_box = {}

    def run():
        result_box["r"] = unittest.TextTestRunner(verbosity=1).run(suite)

    tracer.runfunc(run)
    counts = tracer.results().counts  # {(filename, lineno): hits}

    hit = {}
    for (fn, ln), n in counts.items():
        fn = os.path.realpath(fn)  # test modules insert "evals/.." on sys.path, so paths arrive unnormalized
        if fn.startswith(PKG + os.sep) and fn.endswith(".py"):
            hit.setdefault(fn, set()).add(ln)

    out = os.path.join(ROOT, args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tf = th = 0
    with open(out, "w") as f:
        f.write("TN:\n")
        for name in sorted(os.listdir(PKG)):
            if not name.endswith(".py"):
                continue
            path = os.path.join(PKG, name)
            lines = executable_lines(path)
            got = hit.get(path, set()) & lines
            f.write("SF:%s\n" % os.path.relpath(path, ROOT))
            for ln in sorted(lines):
                f.write("DA:%d,%d\n" % (ln, 1 if ln in got else 0))
            f.write("LF:%d\nLH:%d\nend_of_record\n" % (len(lines), len(got)))
            tf += len(lines)
            th += len(got)
    pct = 100.0 * th / tf if tf else 100.0
    print("coverage: %.1f%% (%d/%d lines) -> %s" % (pct, th, tf, os.path.relpath(out, ROOT)))
    r = result_box.get("r")
    sys.exit(0 if r and r.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
