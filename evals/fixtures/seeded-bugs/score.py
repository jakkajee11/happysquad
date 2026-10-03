#!/usr/bin/env python3
"""Score seeded-bug recall (spec §18.2) against a reviewer's output.

Usage:
  python3 evals/fixtures/seeded-bugs/score.py <REVIEW out.json>
  python3 evals/fixtures/seeded-bugs/score.py --md <review.md>   # 0.16.2-style table

Matching rule: a finding is a candidate for a bug when its file's basename equals
the bug's file and its desc (lowercased) contains at least one of the bug's keywords.
Among a bug's candidates: any severity=="blocker" -> caught; else any "major" -> partial;
else -> miss.
"""
import json
import re
import sys

BUGS = {
    "B-A": {"file": "machine.py", "keywords": ["prefix", "same_ref", "ref", "mismatch"]},
    "B-B": {"file": "gates.py", "keywords": ["exit", "test_cmds", "agent", "ignored"]},
    "B-C": {"file": "gitutil.py", "keywords": ["index", "git_index_file", "real index", "snapshot"]},
}

_ROW = re.compile(r"^\|\s*(R-\d+)\s*\|\s*(\w+)\s*\|\s*(\w+)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|")


def load_json_findings(path):
    data = json.load(open(path, encoding="utf-8"))
    findings = data["findings"] if isinstance(data, dict) else data
    return [{"id": f.get("id"), "severity": f.get("severity"), "file": f.get("file"), "desc": f.get("desc") or ""}
            for f in findings]


def load_md_findings(path):
    out = []
    for line in open(path, encoding="utf-8"):
        m = _ROW.match(line)
        if not m:
            continue
        rid, severity, _tag, fileline, desc = m.groups()
        file_ = fileline.rsplit(":", 1)[0] if fileline and fileline != "-" else None
        out.append({"id": rid, "severity": severity.lower(), "file": file_, "desc": desc})
    return out


def basename(path):
    return (path or "").replace("\\", "/").rsplit("/", 1)[-1]


def score(findings, bugs):
    results = {}
    for bug_id, spec in bugs.items():
        candidates = [
            f for f in findings
            if basename(f["file"]) == spec["file"]
            and any(kw.lower() in (f["desc"] or "").lower() for kw in spec["keywords"])
        ]
        blockers = [f for f in candidates if f["severity"] == "blocker"]
        majors = [f for f in candidates if f["severity"] == "major"]
        if blockers:
            results[bug_id] = ("caught", blockers[0]["id"])
        elif majors:
            results[bug_id] = ("partial", majors[0]["id"])
        else:
            results[bug_id] = ("miss", None)
    return results


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--md":
        findings = load_md_findings(argv[1])
    elif argv:
        findings = load_json_findings(argv[0])
    else:
        sys.exit(__doc__)

    results = score(findings, BUGS)
    caught = partials = 0
    for bug_id in BUGS:
        verdict, fid = results[bug_id]
        if verdict == "caught":
            caught += 1
        elif verdict == "partial":
            partials += 1
        tag = " (%s)" % fid if fid else ""
        print("  %-4s %s%s" % (bug_id, verdict, tag))
    print("recall: %d/%d (partials: %d)" % (caught, len(BUGS), partials))


if __name__ == "__main__":
    main()
