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


def read(p):
    with open(p) as f:
        return f.read()


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)


def happy(phase, root, pd, iteration):
    """Default happy-path artifacts for the toy repo: add mul() to calc.js."""
    if phase == "ARCHITECT":
        write(os.path.join(pd, "design.md"), "# Design\n\nAC-1: mul(a,b) returns a*b.\n\nFiles: src/calc.js, test/mul.test.js\n")
        return {"phase": "ARCHITECT", "size": "S", "design": "design.md", "assumptions": [],
                "ac": [{"id": "AC-1", "text": "mul(a,b) returns a*b"}],
                "workstreams": [{"name": "main", "owned": ["src/calc.js"], "depends_on": [], "ac": ["AC-1"]}],
                "test_owned": {"main": ["test/mul.test.js"]}}
    if phase == "IMPLEMENT":
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
        return {"phase": "IMPLEMENT", "workstream": None, "files": ["src/calc.js"], "build_cmds": [], "unmet_ac": []}
    if phase == "TEST":
        tf = os.path.join(root, "test", "mul.test.js")
        write(tf, 'import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
                  'import { mul } from "../src/calc.js";\n\ntest("mul", () => {\n  assert.equal(mul(3, 4), 12);\n});\n')
        write(os.path.join(pd, "test-report.md"), "all pass; AC-1 -> test/mul.test.js::mul\n")
        write(os.path.join(pd, "test-output.txt"), "(fake)\n")
        # red proof: the import of mul fails at base (compile-red)
        write(os.path.join(pd, "redgreen.json"), json.dumps(
            {"ref": os.environ.get("FAKE_PROOF_REF", ""), "rows": [{"test": "test/mul.test.js", "kind": "compile",
                                                                       "evidence": "SyntaxError: The requested module does not provide an export named 'mul'"}]}))
        return {"phase": "TEST", "workstream": None, "test_cmds": [], "coverage_report": None,
                "test_files": ["test/mul.test.js"], "new_tests": ["test/mul.test.js"],
                "ac_map": {"AC-1": ["test/mul.test.js::mul"]}, "redgreen": "redgreen.json", "findings": []}
    if phase == "REVIEW":
        write(os.path.join(pd, "review.md"), "# Review\n\nClean.\n")
        return {"phase": "REVIEW", "mode": "single", "report": "review.md", "findings": [],
                "axes": {"REQ": "PASS", "SEC": "PASS", "PERF": "PASS", "STD": "PASS", "SIMPL": "PASS", "TEST": "PASS"}}
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
    phase = {"architecter": "ARCHITECT", "implementer": "IMPLEMENT", "tester": "TEST", "chief reviewer": "REVIEW"}[
        re.search(r"You are the \*\*([a-z ]+)\*\*", prompt).group(1)]
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
        out = happy(phase, root, pd, iteration)
    if entry and entry.get("skip_out"):
        return
    write(args.out_file, json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
