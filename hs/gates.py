"""Gates (spec §7). `run_gates` is what `hs _gates <phase-dir>` executes, detached from `advance`.

Output file: runs/<id>/gates-<PHASE>-i<N>.json  (atomic rename when done)
"""
import os

from . import coverage, provenance, state as S


def _phase_dir_name(pd):
    return os.path.basename(pd.rstrip("/"))


# gate subprocesses see HS_GATE=1 so a fixture can behave differently under the gate than under an agent
GATE_ENV = dict(os.environ, HS_GATE="1")


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


def gate_build(root, rdir, phase_dir, out, cfg):
    cmds = []
    if cfg.get("build_cmd"):
        cmds.append(("config", cfg["build_cmd"]))
    accepted, rejected = _agent_cmds(out.get("build_cmds"), cfg, "build")
    cmds.extend(("agent", c) for c in accepted)
    results = []
    ok = True
    for i, (src, c) in enumerate(cmds):
        log = os.path.join(phase_dir, "logs", "build-%d.log" % i)
        code, text, secs = provenance.run_cmd(c, root, cfg["gate_timeout"], log, env=GATE_ENV)
        results.append({"cmd": c, "source": src, "exit": code, "secs": secs, "log": os.path.relpath(log, root),
                        "tail": text[-1500:]})
        if code != 0:
            ok = False
            break
    return {"gate": "build", "ok": ok, "cmds": results,
            "untrusted": [{"cmd": c, "reason": r} for c, r in rejected]}


def gate_test(root, rdir, phase_dir, out, cfg, impl_files):
    cmds = []
    if cfg.get("test_cmd"):
        cmds.append(("config", cfg["test_cmd"]))
    accepted, rejected = _agent_cmds(out.get("test_cmds"), cfg, "test")
    cmds.extend(("agent", c) for c in accepted)
    results = []
    tests_ok = True
    for i, (src, c) in enumerate(cmds):
        log = os.path.join(phase_dir, "logs", "test-%d.log" % i)
        code, text, secs = provenance.run_cmd(c, root, cfg["gate_timeout"], log, env=GATE_ENV)
        results.append({"cmd": c, "source": src, "exit": code, "secs": secs, "log": os.path.relpath(log, root),
                        "tail": text[-1500:]})
        if code != 0:
            tests_ok = False
    report = out.get("coverage_report") or cfg.get("coverage_report")
    cov = coverage.parse(os.path.join(root, report) if report else None)
    per_file = coverage.per_file_for(cov, impl_files, root) if cov["status"] == "ok" else {}
    # accept a phase-dir-relative name (the contract) or a root-relative path (what `hs redgreen` prints)
    rg_rel = out.get("redgreen") or "redgreen.json"
    rg = None
    for cand in (os.path.join(phase_dir, rg_rel), os.path.join(root, rg_rel), os.path.join(phase_dir, "redgreen.json")):
        if os.path.isfile(cand):
            rg = S.read_json(cand)
            break
    return {"gate": "test", "ok": tests_ok, "tests": "pass" if tests_ok else "fail", "cmds": results,
            "coverage": {"status": cov["status"], "total": cov["total"], "per_file": per_file, "report": report},
            "redgreen": rg,
            "untrusted": [{"cmd": c, "reason": r} for c, r in rejected]}


def run_gates(root, rdir, phase_dir, cfg):
    """Entry for `hs _gates`. Reads out.json + state, writes gates file atomically."""
    out = S.read_json(os.path.join(phase_dir, "out.json"))
    st = S.load_state(rdir)
    phase = out["phase"]
    result = {"phase_dir": os.path.relpath(phase_dir, root), "started_at": S.now()}
    if phase == "IMPLEMENT":
        result.update(gate_build(root, rdir, phase_dir, out, cfg))
    elif phase == "TEST":
        impl_files = []
        for pd in st.get("impl_phase_dirs", []):
            io = S.read_json(os.path.join(root, pd, "out.json")) or {}
            impl_files.extend(io.get("files", []))
        result.update(gate_test(root, rdir, phase_dir, out, cfg, impl_files))
    else:
        result.update({"gate": "none", "ok": True})
    result["finished_at"] = S.now()
    S.atomic_write_json(gates_file(rdir, phase_dir), result)
    return result
