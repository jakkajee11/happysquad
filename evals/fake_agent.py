#!/usr/bin/env python3
"""Fake agent for $0 e2e tests.

Usage: fake_agent.py <prompt_file> <out_file> --scenario <name> [--step N]

Reads the rendered prompt (to find phase, phase_dir, repo root), then writes the phase's
artifacts + out.json according to the scenario. Scenarios live in evals/scenarios/<name>.json
and map "<PHASE>[-i<N>]" -> {"out": {...}, "files": {"relpath": "content"}, "tests_pass": bool}.
The default behaviour (no scenario entry) is a happy path on the toy repo.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Second workstream used by the parallel scenarios: util owns src/util.js / test/clamp.test.js
# (AC-2: clamp(x, lo, hi)). ws None/"calc"/anything else keeps the original mul() path.
UTIL_SRC = "export function clamp(x, lo, hi) {\n  return Math.min(Math.max(x, lo), hi);\n}\n"
UTIL_SRC_DEP = ('import { mul } from "./calc.js"; // unused; proves the calc -> util wave ordering\n\n'
                + UTIL_SRC)
UTIL_TEST = ('import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
             'import { clamp } from "../src/util.js";\n\ntest("clamp", () => {\n'
             '  assert.equal(clamp(5, 0, 10), 5);\n  assert.equal(clamp(-5, 0, 10), 0);\n'
             '  assert.equal(clamp(15, 0, 10), 10);\n});\n')


def read(p):
    with open(p) as f:
        return f.read()


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)


def happy(phase, root, pd, iteration, ws=None, axis=None):
    """Default happy-path artifacts for the toy repo: add mul() to calc.js (ws None/"calc"),
    or clamp() to util.js (ws "util", used by the parallel scenarios)."""
    if phase == "ARCHITECT":
        write(os.path.join(pd, "design.md"), "# Design\n\nAC-1: mul(a,b) returns a*b.\n\nFiles: src/calc.js, test/mul.test.js\n")
        return {"phase": "ARCHITECT", "size": "S", "design": "design.md", "assumptions": [],
                "ac": [{"id": "AC-1", "text": "mul(a,b) returns a*b"}],
                "workstreams": [{"name": "main", "owned": ["src/calc.js"], "depends_on": [], "ac": ["AC-1"]}],
                "test_owned": {"main": ["test/mul.test.js"]}}
    if phase == "IMPLEMENT":
        if ws == "util":
            calc = os.path.join(root, "src", "calc.js")
            dep_aware = os.path.isfile(calc) and "mul" in read(calc)
            write(os.path.join(root, "src", "util.js"), UTIL_SRC_DEP if dep_aware else UTIL_SRC)
            write(os.path.join(pd, "implementation.md"), "- src/util.js: add clamp()\n")
            return {"phase": "IMPLEMENT", "workstream": "util", "files": ["src/util.js"], "build_cmds": [], "unmet_ac": []}
        src = os.path.join(root, "src", "calc.js")
        s = read(src)
        correct_mul = "export function mul(a, b) {\n  return a * b;\n}"
        # hook: a prior iteration's IMPLEMENT may have written a *buggy* mul() (see
        # tests-fail-with-findings.json); replace it with the correct body instead of
        # appending a duplicate `export function mul` declaration.
        if re.search(r"export function mul\(a, b\) \{[^}]*\}", s):
            s = re.sub(r"export function mul\(a, b\) \{[^}]*\}", correct_mul, s)
            write(src, s)
        elif "export function mul" not in s:
            write(src, s + "\n" + correct_mul + "\n")
        write(os.path.join(pd, "implementation.md"), "- src/calc.js: add mul()\n")
        return {"phase": "IMPLEMENT", "workstream": ws, "files": ["src/calc.js"], "build_cmds": [], "unmet_ac": []}
    if phase == "TEST":
        if ws == "util":
            write(os.path.join(root, "test", "clamp.test.js"), UTIL_TEST)
            write(os.path.join(pd, "test-report.md"), "all pass; AC-2 -> test/clamp.test.js::clamp\n")
            write(os.path.join(pd, "test-output.txt"), "(fake)\n")
            write(os.path.join(pd, "redgreen.json"), json.dumps(
                {"ref": os.environ.get("FAKE_PROOF_REF", ""), "rows": [{"test": "test/clamp.test.js", "kind": "compile",
                                                                          "evidence": "Error [ERR_MODULE_NOT_FOUND]: Cannot find module '../src/util.js'"}]}))
            return {"phase": "TEST", "workstream": "util", "test_cmds": [], "coverage_report": None,
                    "test_files": ["test/clamp.test.js"], "new_tests": ["test/clamp.test.js"],
                    "ac_map": {"AC-2": ["test/clamp.test.js::clamp"]}, "redgreen": "redgreen.json", "findings": [],
                    "mutations": [{"ac": "AC-2", "file": "src/util.js", "find": "Math.min(Math.max(x, lo), hi)",
                                   "replace": "Math.max(x, lo)", "tests": ["test/clamp.test.js"]}]}
        tf = os.path.join(root, "test", "mul.test.js")
        write(tf, 'import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
                  'import { mul } from "../src/calc.js";\n\ntest("mul", () => {\n  assert.equal(mul(3, 4), 12);\n});\n')
        write(os.path.join(pd, "test-report.md"), "all pass; AC-1 -> test/mul.test.js::mul\n")
        write(os.path.join(pd, "test-output.txt"), "(fake)\n")
        # red proof: the import of mul fails at base (compile-red)
        write(os.path.join(pd, "redgreen.json"), json.dumps(
            {"ref": os.environ.get("FAKE_PROOF_REF", ""), "rows": [{"test": "test/mul.test.js", "kind": "compile",
                                                                       "evidence": "SyntaxError: The requested module does not provide an export named 'mul'"}]}))
        return {"phase": "TEST", "workstream": ws, "test_cmds": [], "coverage_report": None,
                "test_files": ["test/mul.test.js"], "new_tests": ["test/mul.test.js"],
                "ac_map": {"AC-1": ["test/mul.test.js::mul"]}, "redgreen": "redgreen.json", "findings": [],
                "mutations": [{"ac": "AC-1", "file": "src/calc.js", "find": "return a * b;", "replace": "return a + b;",
                               "tests": ["test/mul.test.js"]}]}
    if phase == "REVIEW":
        write(os.path.join(pd, "review.md"), "# Review\n\nClean.\n")
        return {"phase": "REVIEW", "mode": "single", "report": "review.md", "findings": [],
                "axes": {"REQ": "PASS", "SEC": "PASS", "PERF": "PASS", "STD": "PASS", "SIMPL": "PASS", "TEST": "PASS"}}
    if phase == "SPECIALIST":
        write(os.path.join(pd, axis + ".md"), "# %s review\n\nClean.\n" % axis)
        return {"phase": "SPECIALIST", "axis": axis, "report": axis + ".md", "findings": []}
    raise SystemExit("unknown phase %s" % phase)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt_file")
    ap.add_argument("out_file")
    ap.add_argument("--scenario", default="pass-first")
    args = ap.parse_args()

    prompt = read(args.prompt_file)
    m = re.search(r"Run `([^`]+)`, iteration (\d+)", prompt)
    run_id, iteration = m.group(1), int(m.group(2))
    role = re.search(r"You are the \*\*([a-z ]+)\*\*", prompt).group(1)
    axis = None
    if role.endswith("specialist reviewer"):
        phase, axis = "SPECIALIST", role.split()[0]
    else:
        phase = {"architecter": "ARCHITECT", "implementer": "IMPLEMENT", "tester": "TEST", "chief reviewer": "REVIEW"}[role]
    ws_m = re.search(r"workstream `([^`]+)`", prompt)
    ws = ws_m.group(1) if ws_m and ws_m.group(1) != "(none)" else None
    pd = os.path.dirname(os.path.abspath(args.out_file))
    root = os.getcwd()

    scen_path = os.path.join(HERE, "scenarios", args.scenario + ".json")
    scen = json.load(open(scen_path)) if os.path.isfile(scen_path) else {}
    phase_dir_name = os.path.basename(os.path.dirname(os.path.abspath(args.out_file)))
    entry = scen.get(phase_dir_name) or scen.get("%s-i%d" % (phase, iteration)) or scen.get(phase)

    # the proof ref the prompt names, so redgreen.json matches what the engine expects
    pr = re.search(r"--ref (\S+) --tests", prompt)
    if pr and pr.group(1) != "(none)":
        os.environ["FAKE_PROOF_REF"] = pr.group(1)

    if entry and entry.get("files"):
        for rel, content in entry["files"].items():
            write(os.path.join(root, rel), content)
    if entry and "out" in entry:
        out = entry["out"]
        for rel, content in (entry.get("artifacts") or {}).items():
            write(os.path.join(pd, rel), content)
        if phase == "TEST" and "redgreen" in entry:
            rg = dict(entry["redgreen"])
            rg.setdefault("ref", os.environ.get("FAKE_PROOF_REF", ""))
            write(os.path.join(pd, "redgreen.json"), json.dumps(rg))
    else:
        out = happy(phase, root, pd, iteration, ws=ws, axis=axis)
    if entry and entry.get("skip_out"):
        return
    write(args.out_file, json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
