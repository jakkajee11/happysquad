"""Gates (spec §7). `run_gates` is what the detached `hs _gates <phase-dir>` child executes.

Output file: runs/<id>/gates-<phase-dir-basename>.json (atomic rename when done).
Gate kinds by the phase dir's out.json: IMPLEMENT→build, TEST→test, CONFLICT→integration,
FIX (inner loop)→verify + build + test.
"""
import fnmatch
import os
import re
import subprocess

from . import coverage, provenance, redgreen, state as S

# gate subprocesses see HS_GATE=1 so a fixture can behave differently under the gate than under an agent
GATE_ENV = dict(os.environ, HS_GATE="1")


def _phase_dir_name(pd):
    return os.path.basename(pd.rstrip("/"))


def gates_file(rdir, phase_dir):
    return os.path.join(rdir, "gates-%s.json" % _phase_dir_name(phase_dir))


def _agent_cmds(cmds, cfg, kind):
    """Filter agent-supplied commands through provenance. Returns (accepted, rejected[(cmd, reason)])."""
    ok, bad = [], []
    config_cmds = [cfg.get("build_cmd"), cfg.get("test_cmd")]
    for c in cmds or []:
        good, why = provenance.classify(c, config_cmds, cfg.get("allowed_flags", []), for_verify=(kind == "verify"))
        (ok if good else bad).append((c, why))
    return [c for c, _ in ok], bad


def _run_all(root, phase_dir, cmds, cfg, prefix, stop_on_fail=True):
    # the coverage report's directory is commonly gitignored and therefore absent in a fresh worktree
    rep = cfg.get("coverage_report")
    if rep and os.path.dirname(rep):
        os.makedirs(os.path.join(root, os.path.dirname(rep)), exist_ok=True)
    results, ok = [], True
    for i, (src, c) in enumerate(cmds):
        log = os.path.join(phase_dir, "logs", "%s-%d.log" % (prefix, i))
        code, text, secs = provenance.run_cmd(c, root, cfg["gate_timeout"], log, env=GATE_ENV)
        results.append({"cmd": c, "source": src, "exit": code, "secs": secs, "log": os.path.relpath(log, root),
                        "tail": text[-1500:]})
        if code != 0:
            ok = False
            if stop_on_fail:
                break
    return ok, results


def gate_build(root, rdir, phase_dir, out, cfg):
    cmds = [("config", cfg["build_cmd"])] if cfg.get("build_cmd") else []
    accepted, rejected = _agent_cmds(out.get("build_cmds"), cfg, "build")
    cmds.extend(("agent", c) for c in accepted)
    ok, results = _run_all(root, phase_dir, cmds, cfg, "build")
    return {"gate": "build", "ok": ok, "cmds": results, "untrusted": [{"cmd": c, "reason": r} for c, r in rejected]}


# --- coverage helpers ---------------------------------------------------------

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def added_line_numbers(root, base_ref, path):
    """Set of line numbers added vs base_ref, or the string 'all' for a file absent at base_ref."""
    if base_ref:
        p = subprocess.run(["git", "cat-file", "-e", "%s:%s" % (base_ref, path)], cwd=root, capture_output=True)
        if p.returncode != 0:
            return "all"
        d = subprocess.run(["git", "diff", "-U0", base_ref, "--", path], cwd=root, capture_output=True, text=True)
        added = set()
        for l in d.stdout.splitlines():
            m = _HUNK.match(l)
            if m:
                start = int(m.group(1)); n = int(m.group(2)) if m.group(2) is not None else 1
                added.update(range(start, start + n))
        return added
    return "all"


def coverage_for_gate(root, cov, files, base_ref, rule):
    """per_file values the verdict gates on, plus the list of files the rule could not verify."""
    if cov.get("status") != "ok":
        return {}, []
    if rule == "file":
        pf = coverage.per_file_for(cov, files, root)
        return pf, [f for f, v in pf.items() if v is None]
    added = {}
    for f in files:
        a = added_line_numbers(root, base_ref, f)
        added[f] = a if a == "all" else a
    # delta_for wants sets for diffs and the literal "all" for new files; map "all" to every executable line
    lines = cov.get("lines") or {}
    norm = {}
    for f, a in added.items():
        if a == "all":
            k = coverage._match_key(lines, f, root)
            norm[f] = set(lines[k].keys()) if k is not None else "all"
        else:
            norm[f] = a
    pf = coverage.delta_for(cov, files, root, norm)
    return pf, [f for f, v in pf.items() if v is None]


def _baseline(root, rdir, cfg, base_ref):
    """The full suite's result at base_ref, run once per run and cached in the run dir."""
    path = os.path.join(rdir, "baseline-tests.json")
    bl = S.read_json(path)
    if bl and bl.get("ref") == base_ref:
        return bl
    rep = cfg.get("coverage_report")
    bl = redgreen.baseline(root, base_ref, cfg["test_cmd"], cfg["gate_timeout"],
                           mkdirs=[os.path.dirname(rep)] if rep else (), env=GATE_ENV)
    S.atomic_write_json(path, bl)
    return bl

def suite_status(root, rdir, cfg, base_ref, results):
    """tests: pass | fail | pre-existing, for a list of test-command results.

    pre-existing = only the config suite failed, it fails at base_ref too, and every failing-test line
    at head also fails there. Anything unknown (agent command failed, timeout, no recognisable failure
    lines, base green or unrunnable) stays `fail`, so a real regression is never waved through.
    """
    bad = [r for r in results if r["exit"] != 0]
    if not bad:
        return {"tests": "pass"}
    if any(r["source"] != "config" or r["exit"] == -9 for r in bad) or not base_ref:
        return {"tests": "fail"}
    with open(os.path.join(root, bad[0]["log"])) as f:
        head = redgreen.failure_lines(f.read())
    bl = _baseline(root, rdir, cfg, base_ref)
    new = sorted(head - set(bl["failures"]))
    pre = bool(head) and not new and bl["exit"] not in (0, None, -9)
    return {"tests": "pre-existing" if pre else "fail", "tests_new": new,
            "tests_pre": sorted(head & set(bl["failures"])), "baseline": {"ref": bl["ref"], "exit": bl["exit"]}}

def gate_test(root, rdir, phase_dir, out, cfg, impl_files, base_ref, rule):
    cmds = [("config", cfg["test_cmd"])] if cfg.get("test_cmd") else []
    accepted, rejected = _agent_cmds(out.get("test_cmds"), cfg, "test")
    cmds.extend(("agent", c) for c in accepted)
    _, results = _run_all(root, phase_dir, cmds, cfg, "test", stop_on_fail=False)
    ts = suite_status(root, rdir, cfg, base_ref, results)
    tests_ok = ts["tests"] != "fail"
    report = out.get("coverage_report") or cfg.get("coverage_report")
    cov = coverage.parse(os.path.join(root, report) if report else None)
    per_file, unverified = coverage_for_gate(root, cov, impl_files, base_ref, rule)
    rg_rel = out.get("redgreen") or "redgreen.json"
    rg = None
    for cand in (os.path.join(phase_dir, rg_rel), os.path.join(root, rg_rel), os.path.join(phase_dir, "redgreen.json")):
        if os.path.isfile(cand):
            rg = S.read_json(cand)
            break
    return dict(ts, gate="test", ok=tests_ok, cmds=results,
                coverage={"status": cov["status"], "total": cov["total"], "per_file": per_file,
                          "unverified": unverified, "rule": rule, "report": report},
                redgreen=rg, untrusted=[{"cmd": c, "reason": r} for c, r in rejected])


def gate_integration(root, rdir, phase_dir, cfg, base_ref):
    cmds = []
    if cfg.get("build_cmd"):
        cmds.append(("config", cfg["build_cmd"]))
    if cfg.get("test_cmd"):
        cmds.append(("config", cfg["test_cmd"]))
    ok, results = _run_all(root, phase_dir, cmds, cfg, "integration")
    res = {"gate": "integration", "ok": ok, "cmds": results}
    if not ok and len(results) == len(cmds) and cfg.get("test_cmd"):
        # build passed, only the suite failed: pre-existing failures must not send the run back to the architect
        res.update(suite_status(root, rdir, cfg, base_ref, results[-1:]))
        res["ok"] = res["tests"] == "pre-existing"
    return res


def gate_verify(root, phase_dir, verifies, cfg):
    """Run each finding's verify command. Returns {id: pass|fail|manual|untrusted}."""
    res = {}
    config_cmds = [cfg.get("build_cmd"), cfg.get("test_cmd")]
    for i, (fid, cmd) in enumerate(sorted(verifies.items())):
        if not cmd or cmd == "manual":
            res[fid] = "manual"
            continue
        good, why = provenance.classify(cmd, config_cmds, cfg.get("allowed_flags", []), for_verify=True)
        if not good:
            res[fid] = "untrusted"
            continue
        log = os.path.join(phase_dir, "logs", "verify-%s.log" % re.sub(r"[^A-Za-z0-9_-]", "_", fid))
        code, _, _ = provenance.run_cmd(cmd, root, 300, log, env=GATE_ENV)
        res[fid] = "pass" if code == 0 else "fail"
    return res


def ownership_check(root, changed, workstreams, test_owned, generated):
    """Every changed file must match exactly one workstream's owned ∪ test_owned globs (generated exempt)."""
    violations = []
    for f in changed:
        if any(fnmatch.fnmatch(f, g) for g in generated or []):
            continue
        owners = []
        for w in workstreams:
            globs = list(w.get("owned", [])) + list((test_owned or {}).get(w["name"], []))
            if any(fnmatch.fnmatch(f, g) or f == g for g in globs):
                owners.append(w["name"])
        if len(owners) != 1:
            violations.append({"file": f, "owners": owners, "reason": "unowned" if not owners else "multi-owner"})
    return violations


def run_gates(root, rdir, phase_dir, cfg):
    """Entry for `hs _gates`. Reads out.json + state, writes the gates file atomically."""
    out = S.read_json(os.path.join(phase_dir, "out.json")) or {}
    st = S.load_state(rdir) or {}
    phase = out.get("phase")
    ws = out.get("workstream")
    result = {"phase_dir": os.path.relpath(phase_dir, root), "phase": phase, "workstream": ws, "started_at": S.now()}
    rule = cfg.get("coverage_rule", "delta")
    if phase == "IMPLEMENT":
        result.update(gate_build(root, rdir, phase_dir, out, cfg))
    elif phase == "TEST":
        # single-mode runs key impl files by the lone workstream's name; the tester's out.json says null
        wif = st.get("ws_impl_files") or {}
        if ws:
            files = list(wif.get(ws, []))
        else:
            files = sorted({f for lst in wif.values() for f in lst})
        result.update(gate_test(root, rdir, phase_dir, out, cfg, files, st.get("base_ref"), rule))
    elif phase == "CONFLICT":
        result.update(gate_integration(root, rdir, phase_dir, cfg, st.get("base_ref")))
    elif phase == "FIX":
        verifies = st.get("inner_verify") or {}
        result["verify"] = gate_verify(root, phase_dir, verifies, cfg)
        files = []
        for lst in (st.get("ws_impl_files") or {}).values():
            files.extend(lst)
        fix_out = S.read_json(os.path.join(phase_dir, "agent-out.json")) or {}
        if fix_out.get("phase") == "IMPLEMENT":
            files.extend(fix_out.get("files", []))
        b = gate_build(root, rdir, phase_dir, {"build_cmds": fix_out.get("build_cmds")}, cfg)
        t = gate_test(root, rdir, phase_dir, fix_out if fix_out.get("phase") == "TEST" else {}, cfg,
                      sorted(set(files)), st.get("base_ref"), rule)
        result.update({"gate": "fix", "build": b, "test": t, "tests": t["tests"], "tests_new": t.get("tests_new"),
                       "tests_pre": t.get("tests_pre"), "coverage": t["coverage"],
                       "redgreen": t["redgreen"], "cmds": b["cmds"] + t["cmds"],
                       "ok": b["ok"] and all(v in ("pass", "manual") for v in result["verify"].values())})
    else:
        result.update({"gate": "none", "ok": True})
    result["finished_at"] = S.now()
    S.atomic_write_json(gates_file(rdir, phase_dir), result)
    return result
