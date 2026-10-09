"""State machine (spec §8) — P1a scope.

ARCHITECT → IMPLEMENT (DAG waves) → TEST (DAG waves) → CONFLICT → RISK → SPECIALISTS → REVIEW
  → COMPLETE
  → FAIL: INNER_FIX → gates(verify+build+test) → REVIEW(delta)  (all blockers verifiable)
  → FAIL: full round to IMPLEMENT / TEST / ARCHITECT            (otherwise)
  → BLOCKED (validation | gate | convergence | agent | config)

Every mutating entry point takes the run lock. `next_action` is read-only.
"""
import hashlib
import os
import re
import subprocess
import sys

from . import gates, gitutil, render, risk as R, schemas, state as S

AGENT_FOR = {"ARCHITECT": "architecter", "IMPLEMENT": "implementer", "TEST": "tester", "REVIEW": "reviewer",
             "SPECIALIST": "specialist"}
PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HS_BIN = os.path.join(PLUGIN_ROOT, "bin", "hs")
TERMINAL = ("COMPLETE", "BLOCKED")


def slug(text, n=6):
    words = re.findall(r"[A-Za-z0-9]+", text)[:n]
    return "-".join(w.lower() for w in words) or "task"


def phase_dir_name(phase, iteration, ws=None, retry=0, extra=None):
    name = "%s-i%d" % (phase, iteration)
    if extra:
        name += "-" + extra
    if ws:
        name += "-" + ws
    if retry:
        name += "-r%d" % retry
    return name


# --- pure helpers (unit-tested) ------------------------------------------------

def ready_workstreams(workstreams, key):
    """Workstreams whose `key` status is pending and whose depends_on are all done for `key`."""
    done = {w["name"] for w in workstreams if w.get(key) == "done"}
    return [w["name"] for w in workstreams
            if w.get(key, "pending") == "pending" and all(d in done for d in w.get("depends_on", []))]


def fingerprint(f):
    desc = (f.get("desc") or "").lower()
    desc = re.sub(r"[\d'\"`]+", "", desc)
    desc = " ".join(t for t in desc.split() if len(t) <= 40)
    return hashlib.sha1(("%s|%s|%s" % (f.get("tag"), f.get("file"), desc)).encode()).hexdigest()[:16]


def converge(findings_state, blockers, iteration, route, arch_iterations, zero_progress):
    """Apply spec §8.3 to this review's blockers.

    Returns (new_findings_state, forced_route|None, block_reason|None, resolved_count, repeat_count).
    findings_state: {fp: {"id","seen":[...],"routes":[...]}}
    """
    fs = {k: dict(v, seen=list(v["seen"]), routes=list(v["routes"])) for k, v in findings_state.items()}
    by_id = {v["id"]: k for k, v in fs.items()}
    seen_now = set()
    for b in blockers:
        if b.get("source") == "gate":
            continue
        fp = by_id.get(b.get("prior_id")) if b.get("prior_id") else None
        fp = fp or fingerprint(b)
        if fp not in fs:
            fs[fp] = {"id": b["id"], "seen": [], "routes": []}
        if iteration not in fs[fp]["seen"]:
            fs[fp]["seen"].append(iteration)
            fs[fp]["routes"].append(route)
        seen_now.add(fp)
    prev_open = {k for k, v in findings_state.items() if v["seen"] and v["seen"][-1] == iteration - 1}
    resolved = len(prev_open - seen_now)
    repeats = [k for k in seen_now if len(fs[k]["seen"]) >= 2]
    third = [k for k in seen_now if len(fs[k]["seen"]) >= 3]
    forced = None
    block = None
    for k in seen_now:
        s = fs[k]["seen"]
        if len(s) >= 2 and any(s[0] <= a < iteration for a in arch_iterations):
            block = "blocker %s recurred after an architecter round (seen iterations %s)" % (fs[k]["id"], s)
        elif len(s) >= 3:
            forced = "architecter"
    # zero-progress applies only when there were tracked (reviewer) blockers to resolve
    if block is None and prev_open and resolved == 0:
        if zero_progress >= 1:
            block = "two consecutive rounds resolved zero blockers"
        else:
            forced = forced or "architecter"
    return fs, forced, block, resolved, len(repeats), third


def _same_ref(a, b):
    if not a or not b:
        return False
    a, b = str(a), str(b)
    return (a.startswith(b) or b.startswith(a)) and min(len(a), len(b)) >= 7


def verdict(out, test_gate, threshold, impl_files, new_tests, proof_ref):
    """Spec §6.4 truth table. Returns (blockers, majors, route). Synthetic blockers carry source='gate'.

    `new_tests` must already exclude tests proven red in an earlier iteration.
    """
    blockers, majors = [], []
    for f in out.get("findings", []):
        sev = f["severity"]
        if f["tag"] == "SIMPL" and sev == "blocker":
            sev = "major"
        (blockers if sev == "blocker" else majors if sev == "major" else []).append(f)
    tg = test_gate or {}
    if tg.get("tests") == "fail":
        new = tg.get("tests_new")
        blockers.append({"id": "G-TESTS", "severity": "blocker", "tag": "REQ", "file": None,
                         "desc": "full test suite fails" + (" (new vs base: %s)" % "; ".join(new[:5]) if new else ""),
                         "route": "implementer", "verify": "manual", "source": "gate"})
    elif tg.get("tests") == "pre-existing":
        majors.append({"id": "G-TESTS-PRE", "severity": "major", "tag": "REQ", "file": None,
                       "desc": "suite fails, but only with failures already present at the base ref: %s" % "; ".join((tg.get("tests_pre") or [])[:5]),
                       "route": "implementer", "verify": "manual", "source": "gate"})
    cov = tg.get("coverage") or {}
    if threshold is not None:
        if cov.get("status") == "ok":
            low = {f: v for f, v in (cov.get("per_file") or {}).items() if v is not None and v < threshold}
            if low:
                blockers.append({"id": "G-COV", "severity": "blocker", "tag": "TEST", "file": None,
                                 "desc": "coverage of changed lines below %s: %s" % (threshold, low),
                                 "route": "tester", "verify": "manual", "source": "gate"})
            unv = [f for f, v in (cov.get("per_file") or {}).items() if v is None] or cov.get("unverified") or []
            if unv:
                majors.append({"id": "G-COV-UNVERIFIED", "severity": "major", "tag": "TEST", "file": None,
                               "desc": "coverage unverifiable for %s (no per-line data)" % sorted(unv),
                               "route": "tester", "verify": "manual", "source": "gate"})
        elif cov.get("status") in ("unsupported", "missing"):
            majors.append({"id": "G-COV-UNVERIFIED", "severity": "major", "tag": "TEST", "file": None,
                           "desc": "coverage unverified (%s)" % cov.get("status"), "route": "tester",
                           "verify": "manual", "source": "gate"})
    rg = tg.get("redgreen") or {}
    rows = {r["test"]: r for r in (rg.get("rows") or [])}
    if new_tests:
        bad = []
        for t in new_tests:
            r = rows.get(t)
            if r is None:
                bad.append("%s: no row" % t)
            elif r.get("kind") == "green":
                bad.append("%s: green at ref" % t)
        if rg.get("ref") and proof_ref and not _same_ref(rg.get("ref"), proof_ref):
            bad.append("ref mismatch %s != %s" % (rg.get("ref"), proof_ref))
        if bad:
            blockers.append({"id": "G-RED", "severity": "blocker", "tag": "TEST", "file": None,
                             "desc": "red→green proof incomplete: " + "; ".join(bad), "route": "tester",
                             "verify": "manual", "source": "gate"})
    else:
        majors.append({"id": "G-RED-NONE", "severity": "major", "tag": "TEST", "file": None,
                       "desc": "no red-first proof (no new tests)", "route": "tester", "verify": "manual", "source": "gate"})
    route = None
    if blockers:
        if any(b["tag"] == "CONFLICT" for b in blockers) or any(b["route"] == "architecter" for b in blockers):
            route = "architecter"
        else:
            routes = {b["route"] for b in blockers}
            route = "implementer" if "implementer" in routes else "tester"
    return blockers, majors, route


# --- run lifecycle -----------------------------------------------------------

def start(root, task, cfg, lite=False, driver=None):
    if not gitutil.is_repo(root):
        return {"action": "error", "message": "not a git repository"}
    if not cfg.get("test_cmd"):
        return {"action": "error", "message": "config.test_cmd is null — set it in .happysquad/config.json (BLOCKED cause=config)"}
    gitutil.prune(root)
    ts = S.now().replace("-", "").replace(":", "").replace("T", "-").replace("Z", "")
    run_id = "%s-%s" % (ts, slug(task))
    rdir = S.run_dir(root, run_id)
    os.makedirs(os.path.join(rdir, "prompts"), exist_ok=True)
    with S.locked(rdir):
        base = gitutil.snapshot(root, "%s/base" % run_id)
        st = {
            "run_id": run_id, "task": task, "driver": driver or cfg["driver"],
            "mode": "single", "lite": bool(lite), "lite_forced": bool(lite), "size": None,
            "review_mode": cfg.get("review_mode", "split-on-risk"),
            "base_ref": base, "iter_ref": None, "proof_ref": base, "proven": [],
            "state": "ARCHITECT", "iteration": 1, "inner_pass": 0,
            "gate_retry": 0, "validation_retry": 0, "retry": 0, "gap_count": 0,
            "cap": cfg["lite"]["cap"] if lite else cfg["cap"], "inner_cap": cfg["inner_cap"],
            "coverage_threshold": cfg["coverage_threshold"],
            "cmds": {"build": cfg.get("build_cmd"), "test": cfg.get("test_cmd"), "coverage_report": cfg.get("coverage_report")},
            "workstreams": [], "untestable": [], "test_owned": {}, "ws_impl_files": {},
            "impl_phase_dirs": [], "test_phase_dirs": [], "review_phase_dirs": [],
            "pending": [], "gates": {}, "findings": {}, "arch_iterations": [], "zero_progress": 0,
            "risk": None, "specialists": {}, "specialist_reports": [], "inner_verify": {}, "delta": False,
            "started_at": S.now(),
        }
        S.atomic_write(os.path.join(rdir, "task.md"), task + "\n")
        S.commit(rdir, st, "run.start", data={"base_ref": base, "lite": bool(lite)})
        S.set_current(root, run_id)
    return next_action(root, run_id, cfg)


def start_review_only(root, cfg, base=None, task=None):
    """Review-only run (spec §14 /squad-review): no ARCHITECT/IMPLEMENT/TEST agents.

    The diff vs `base` (default: merge-base with the upstream default branch, else HEAD) is treated
    as a finished single-workstream change: the test gate runs on it, then RISK → SPECIALISTS →
    REVIEW exactly as in a normal run. The verdict routes nowhere; FAIL just reports findings.
    """
    if not gitutil.is_repo(root):
        return {"action": "error", "message": "not a git repository"}
    if not cfg.get("test_cmd"):
        return {"action": "error", "message": "config.test_cmd is null — set it in .happysquad/config.json"}
    gitutil.prune(root)
    if not base:
        base = _default_base(root)
    changed = gitutil.changed_files(root, base)
    if not changed:
        return {"action": "error", "message": "nothing to review: no changes vs %s" % (base or "HEAD")}
    ts = S.now().replace("-", "").replace(":", "").replace("T", "-").replace("Z", "")
    run_id = "%s-review-%s" % (ts, slug(task or "diff vs " + str(base)[:7]))
    rdir = S.run_dir(root, run_id)
    os.makedirs(os.path.join(rdir, "prompts"), exist_ok=True)
    with S.locked(rdir):
        src = [f for f in changed if not _looks_like_test(f)]
        tests = [f for f in changed if _looks_like_test(f)]
        st = {
            "run_id": run_id, "task": task or "Review the changes vs %s" % (base or "HEAD"), "driver": cfg["driver"],
            "mode": "single", "lite": False, "lite_forced": False, "size": None, "review_only": True,
            "review_mode": cfg.get("review_mode", "split-on-risk"),
            "base_ref": base, "iter_ref": None, "proof_ref": base, "proven": [],
            "state": "TEST", "iteration": 1, "inner_pass": 0,
            "gate_retry": 0, "validation_retry": 0, "retry": 0, "gap_count": 0,
            "cap": 1, "inner_cap": 0, "coverage_threshold": cfg["coverage_threshold"],
            "cmds": {"build": cfg.get("build_cmd"), "test": cfg.get("test_cmd"), "coverage_report": cfg.get("coverage_report")},
            "workstreams": [{"name": "diff", "owned": src or changed, "depends_on": [], "ac": [], "impl": "done", "test": "pending"}],
            "untestable": [], "test_owned": {"diff": tests}, "ws_impl_files": {"diff": src},
            "impl_phase_dirs": [], "test_phase_dirs": [], "review_phase_dirs": [],
            "pending": [], "gates": {}, "findings": {}, "arch_iterations": [], "zero_progress": 0,
            "risk": None, "specialists": {}, "specialist_reports": [], "inner_verify": {}, "delta": False,
            "started_at": S.now(),
        }
        S.atomic_write(os.path.join(rdir, "task.md"), st["task"] + "\n")
        S.atomic_write(os.path.join(rdir, "design.md"),
                       "# Review-only run\n\nNo design: the diff vs `%s` is reviewed as-is.\n\nChanged files:\n%s\n"
                       % (base, "\n".join("- " + f for f in changed)))
        # synthetic TEST phase: the gate runs the configured suite + coverage over the diff; no tester agent
        pd = os.path.join(rdir, phase_dir_name("TEST", 1))
        os.makedirs(os.path.join(pd, "logs"), exist_ok=True)
        S.atomic_write_json(os.path.join(pd, "out.json"),
                            {"phase": "TEST", "workstream": None, "test_cmds": [], "coverage_report": None,
                             "test_files": tests, "new_tests": [], "ac_map": {}, "untestable": [], "redgreen": None, "findings": []})
        st["test_phase_dirs"].append(os.path.relpath(pd, root))
        S.commit(rdir, st, "run.start", data={"base_ref": base, "review_only": True, "files": len(changed)})
        _spawn_gates(root, rdir, st, pd, phase="TEST")
        S.commit(rdir, st, "gates.start", phase="TEST", iteration=1, data={"phase_dir": os.path.relpath(pd, root), "review_only": True})
        S.set_current(root, run_id)
    return next_action(root, run_id, cfg)


def _default_base(root):
    for cand in ("origin/main", "origin/master", "main", "master"):
        p = subprocess.run(["git", "merge-base", "HEAD", cand], cwd=root, capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip() and p.stdout.strip() != gitutil.head(root):
            return p.stdout.strip()
    return gitutil.head(root)


def _looks_like_test(path):
    p = path.lower()
    return ("/test/" in "/" + p or "/tests/" in "/" + p or "/__tests__/" in "/" + p or "/spec/" in "/" + p
            or p.endswith((".test.js", ".test.ts", ".test.tsx", ".spec.js", ".spec.ts", "_test.go", "_test.py", "tests.cs"))
            or os.path.basename(p).startswith("test_"))


# --- prompts -----------------------------------------------------------------

def _ws(st, name):
    for w in st.get("workstreams", []):
        if w["name"] == name:
            return w
    return None


def _vars(root, st, cfg, spec):
    """Render variables for one dispatch spec (phase, ws, axis, agent, phase_dir, schema_phase)."""
    rdir = S.run_dir(root, st["run_id"])
    rel = lambda p: os.path.relpath(p, root)
    pd = spec["phase_dir_abs"]
    v = {
        "hs": HS_BIN, "run_id": st["run_id"], "iteration": st["iteration"], "task": st["task"],
        "task_file": rel(os.path.join(rdir, "task.md")),
        "design_path": rel(os.path.join(rdir, "design.md")),
        "phase_dir": rel(pd), "out_file": rel(os.path.join(pd, "out.json")),
        "out_schema": schemas.render(spec["schema_phase"]),
        "base_ref": st.get("base_ref"), "iter_ref": st.get("iter_ref"),
        "proof_ref": st.get("proof_ref") or st.get("base_ref"),
        "build_cmd": st["cmds"].get("build"), "test_cmd": st["cmds"].get("test"),
        "coverage_report": st["cmds"].get("coverage_report"), "threshold": st["coverage_threshold"],
        "feedback_path": rel(os.path.join(rdir, "feedback.md")) if os.path.isfile(os.path.join(rdir, "feedback.md")) else None,
        "implementation_path": None, "test_report_path": None, "gates_summary": None,
        "owned_files": None, "test_owned_files": None, "ac_list": None, "untestable": None,
        "workstream": spec.get("ws") or "null", "agent": spec.get("agent"), "inner_pass": st.get("inner_pass", 0),
        "mode": "delta" if st.get("delta") else ("single" if st["review_mode"] == "single" or st.get("lite") else "split-on-risk"),
        "axis": spec.get("axis"), "axis_checklist": None, "risk_matches": None,
        "specialist_reports": st.get("specialist_reports") or None, "prior_findings": None,
        "lite_note": ("LITE RUN: keep design.md to task summary, acceptance criteria and owned files. One workstream. "
                      "No component breakdown, no sequence diagrams." if st.get("lite") else None),
    }
    w = _ws(st, spec.get("ws")) or (st.get("workstreams") or [None])[0]
    if w:
        v["owned_files"] = w.get("owned")
        v["ac_list"] = w.get("ac")
        v["test_owned_files"] = (st.get("test_owned") or {}).get(w["name"])
    if st.get("untestable"):
        v["untestable"] = ["%s: %s" % (u["ac"], u["reason"]) for u in st["untestable"]]
    if spec.get("agent") == "tester" and spec["schema_phase"] == "TEST":
        v["owned_files"] = v["test_owned_files"]
    impl_dirs = [d for d in st.get("impl_phase_dirs", []) if spec.get("ws") is None or d.endswith("-" + spec["ws"]) or ("-" + spec["ws"] + "-r") in d]
    if impl_dirs:
        v["implementation_path"] = os.path.join(impl_dirs[-1], "implementation.md")
    if st.get("test_phase_dirs"):
        v["test_report_path"] = os.path.join(st["test_phase_dirs"][-1], "test-report.md")
    tg = st.get("last_test_gate")
    if tg:
        cov = tg.get("coverage") or {}
        v["gates_summary"] = "tests=%s coverage_rule=%s coverage_status=%s total=%s per_file=%s unverified=%s" % (
            tg.get("tests"), cov.get("rule"), cov.get("status"), cov.get("total"), cov.get("per_file"), cov.get("unverified"))
        if tg.get("tests_pre"):
            v["gates_summary"] += " failing_at_base_too=%s" % tg["tests_pre"][:10]
    if spec.get("axis"):
        v["axis_checklist"] = os.path.join(PLUGIN_ROOT, "references", "axis-%s.md" % spec["axis"])
        rk = st.get("risk") or {}
        v["risk_matches"] = ["%s (%s: %s)" % (m["file"], m["kind"], m["pattern"]) for m in rk.get("matches", []) if m["axis"] == spec["axis"]] or None
    if spec["phase"] in ("REVIEW", "SPECIALIST"):
        # diff against a tree of the working tree, not the index: new files show, pre-existing untracked ones don't show as deleted
        v["tree_ref"] = gitutil.worktree_tree(root)
        v["changed_files"] = gitutil.changed_files(root, st.get("base_ref"), v["tree_ref"])
        if st.get("delta") and st.get("iter_ref"):
            v["fix_diff"] = "git diff %s %s -- . ':(exclude).happysquad'" % (st["iter_ref"], v["tree_ref"])
            v["fix_files"] = gitutil.changed_files(root, st["iter_ref"], v["tree_ref"])
    if st.get("review_phase_dirs"):
        prev = S.read_json(os.path.join(root, st["review_phase_dirs"][-1], "out.json")) or {}
        rows = ["| id | severity | tag | file:line | desc |", "|---|---|---|---|---|"]
        for f in prev.get("findings", []):
            rows.append("| %s | %s | %s | %s:%s | %s |" % (f["id"], f["severity"], f["tag"], f.get("file"), f.get("line"), f["desc"][:100]))
        v["prior_findings"] = "\n".join(rows) if len(rows) > 2 else None
    return v


_TEMPLATE_FOR = {"ARCHITECT": "architect", "IMPLEMENT": "implement", "TEST": "test", "REVIEW": "review",
                 "SPECIALIST": "specialist", "INNER_FIX": "fix"}


def _render_prompt(root, st, cfg, spec):
    tpl = os.path.join(PLUGIN_ROOT, "prompts", "%s.md" % _TEMPLATE_FOR[spec["phase"]])
    text = render.render_file(tpl, _vars(root, st, cfg, spec))
    rdir = S.run_dir(root, st["run_id"])
    pf = os.path.join(rdir, "prompts", os.path.basename(spec["phase_dir_abs"]) + ".md")
    S.atomic_write(pf, text)
    return pf



def _model_for(st, cfg, agent):
    """The model for an agent dispatch; the escalated iteration's fix agents use escalation.model (spec §8.6)."""
    esc = st.get("escalation")
    if esc and esc.get("iteration") == st.get("iteration") and agent in ("implementer", "tester"):
        return esc["model"]
    return cfg["models"][agent]


# --- what dispatches are needed right now (read-only) ------------------------

def _needed(root, rdir, st, cfg):
    """Dispatch specs for the current state that are not yet pending. Each spec is a dict."""
    phase = st["state"]
    it = st["iteration"]
    pend = {(p["phase"], p.get("ws"), p.get("axis"), p.get("agent")) for p in st.get("pending", [])}
    specs = []

    def spec(phase_, agent, ws=None, axis=None, extra=None, schema_phase=None):
        name = phase_dir_name(phase_ if phase_ != "SPECIALIST" else "SPECIALIST", it, ws=ws, retry=st.get("retry", 0) if phase_ in ("ARCHITECT", "REVIEW") else 0, extra=extra)
        if phase_ == "SPECIALIST":
            name = phase_dir_name("SPECIALIST", it, ws=axis)
        pd = os.path.join(rdir, name)
        return {"phase": phase_, "agent": agent, "ws": ws, "axis": axis, "schema_phase": schema_phase or phase_,
                "model": _model_for(st, cfg, agent), "phase_dir_abs": pd,
                "out_file": os.path.relpath(os.path.join(pd, "out.json"), root)}

    if phase == "ARCHITECT":
        if ("ARCHITECT", None, None, "architecter") not in pend:
            specs.append(spec("ARCHITECT", "architecter"))
    elif phase in ("IMPLEMENT", "TEST"):
        key = "impl" if phase == "IMPLEMENT" else "test"
        agent = "implementer" if phase == "IMPLEMENT" else "tester"
        single = st["mode"] == "single"
        for name in ready_workstreams(st["workstreams"], key):
            ws = None if single else name
            if (phase, ws, None, agent) not in pend:
                sp = spec(phase, agent, ws=ws)
                # per-workstream gate retry suffix
                r = (_ws(st, name) or {}).get("retry_" + key, 0)
                if r:
                    sp["phase_dir_abs"] = os.path.join(rdir, phase_dir_name(phase, it, ws=ws, retry=r))
                    sp["out_file"] = os.path.relpath(os.path.join(sp["phase_dir_abs"], "out.json"), root)
                specs.append(sp)
    elif phase == "SPECIALISTS":
        for axis, status in (st.get("specialists") or {}).items():
            if status == "pending" and ("SPECIALIST", None, axis, "specialist") not in pend:
                specs.append(spec("SPECIALIST", "specialist", axis=axis))
    elif phase == "REVIEW":
        if ("REVIEW", None, None, "reviewer") not in pend:
            sp = spec("REVIEW", "reviewer")
            if st.get("delta"):
                sp["phase_dir_abs"] = os.path.join(rdir, phase_dir_name("REVIEW", it, extra="p%d" % st.get("inner_pass", 0), retry=st.get("retry", 0)))
                sp["out_file"] = os.path.relpath(os.path.join(sp["phase_dir_abs"], "out.json"), root)
            specs.append(sp)
    elif phase == "INNER_FIX":
        order = st.get("inner_order") or []
        done = set(st.get("inner_done") or [])
        for agent in order:
            if agent in done:
                continue
            if ("INNER_FIX", None, None, agent) not in pend:
                sp = spec("INNER_FIX", agent, extra="p%d-%s" % (st.get("inner_pass", 0), agent),
                          schema_phase="IMPLEMENT" if agent == "implementer" else "TEST")
                specs.append(sp)
            break  # sequential: implementer first, then tester
    return specs


def _public(spec):
    return {k: v for k, v in spec.items() if k != "phase_dir_abs"}


def _session_id(root):
    """The Claude session the SessionStart hook recorded (started_at), or None outside a hooked session."""
    sess = S.read_json(os.path.join(S.hs_dir(root), ".session")) or {}
    return sess.get("started_at")


def _count_session_dispatch(root, st):
    """Track dispatches per orchestrator session so the agent-tool driver can be told to hand off."""
    sid = _session_id(root)
    if not sid:
        return
    sd = st.setdefault("session_dispatches", {})
    sd[sid] = sd.get(sid, 0) + 1


def _checkpoint_due(root, st, cfg):
    """Spec §8.9: agent-tool driver only; iteration ≥ checkpoint.iterations or ≥ checkpoint.dispatches in this session."""
    if st.get("driver") != "agent-tool" or st.get("checkpointed_session") == _session_id(root):
        return False
    cp = cfg.get("checkpoint") or {}
    if not cp.get("enabled", True):
        return False
    sid = _session_id(root)
    if not sid:
        return False
    n = (st.get("session_dispatches") or {}).get(sid, 0)
    return st["iteration"] >= cp.get("iterations", 3) or n >= cp.get("dispatches", 12)


def _write_handoff(root, rdir, st):
    rel = lambda p: os.path.relpath(p, root)
    lines = ["# HANDOFF — run %s" % st["run_id"], "",
             "State: **%s** · iteration %d/%d · mode %s · lite %s" % (st["state"], st["iteration"], st["cap"], st.get("mode"), st.get("lite")),
             "Task: %s" % st["task"].splitlines()[0][:120], ""]
    if st.get("pending"):
        lines.append("Pending agents: " + ", ".join("%s%s" % (p["phase"], ("/" + p["ws"]) if p.get("ws") else "") for p in st["pending"]))
    if st.get("review_phase_dirs"):
        lines.append("Last review: %s" % os.path.join(st["review_phase_dirs"][-1], "review.md"))
    if os.path.isfile(os.path.join(rdir, "feedback.md")):
        lines.append("Open feedback: %s" % rel(os.path.join(rdir, "feedback.md")))
    lines += ["", "Next action: open a fresh session in this repo and run `/squad-resume`. The engine continues from disk; nothing is lost."]
    S.atomic_write(os.path.join(rdir, "HANDOFF.md"), "\n".join(lines) + "\n")


def next_action(root, run_id, cfg):
    rdir = S.run_dir(root, run_id)
    st = S.load_state(rdir)
    if st is None:
        return {"action": "error", "message": "no such run %s" % run_id}
    if st["state"] in TERMINAL:
        return _done(root, rdir, st)
    # context checkpoint (spec §8.9): only between phases — never while agents or gates are in flight
    if not st.get("pending") and not st.get("gates") and _checkpoint_due(root, st, cfg):
        with S.locked(rdir):
            st = S.load_state(rdir)
            if st.get("checkpointed_session") != _session_id(root):
                st["checkpointed_session"] = _session_id(root)
                _write_handoff(root, rdir, st)
                S.commit(rdir, st, "checkpoint", phase=st["state"], iteration=st["iteration"],
                         data={"session": _session_id(root), "dispatches": (st.get("session_dispatches") or {}).get(_session_id(root), 0)})
                return {"action": "checkpoint", "handoff": os.path.relpath(os.path.join(rdir, "HANDOFF.md"), root),
                        "state": st["state"], "iteration": st["iteration"],
                        "message": "Context is approaching the smart zone; state is on disk. Continue in a fresh session with /squad-resume."}
    g = st.get("gates", {})
    if g:
        files = [os.path.relpath(os.path.join(rdir, x["file"]), root) for x in g.values()]
        if any(os.path.isfile(os.path.join(rdir, x["file"])) for x in g.values()):
            return {"action": "advance", "reason": "gates finished — run `hs advance`"}
        return {"action": "wait", "for": "gates", "files": files, "since": min(x["started_at"] for x in g.values())}
    pend = st.get("pending", [])
    if pend:
        if any(os.path.isfile(os.path.join(root, p["out_file"])) for p in pend):
            return {"action": "advance", "reason": "out.json present — run `hs advance`"}
        disp = []
        for p in pend:
            pf = os.path.join(rdir, "prompts", os.path.basename(p["phase_dir"]) + ".md")
            disp.append({"phase": p["phase"], "iteration": p["iteration"], "agent": p["agent"],
                         "model": _model_for(st, cfg, p["agent"]), "prompt_file": os.path.relpath(pf, root),
                         "out_file": p["out_file"], "workstream": p.get("ws"), "axis": p.get("axis"), "cwd": None})
        return {"action": "wait", "for": "agents", "files": [p["out_file"] for p in pend],
                "since": min(p["dispatched_at"] for p in pend), "dispatches": disp}
    if st["state"] in ("CONFLICT", "RISK"):
        return {"action": "advance", "reason": "internal state — run `hs advance`"}
    specs = _needed(root, rdir, st, cfg)
    if not specs:
        return {"action": "advance", "reason": "nothing to dispatch — run `hs advance`"}
    if len(specs) == 1:
        d = _public(specs[0])
        return {"action": "dispatch", "phase": d["phase"], "iteration": st["iteration"], "agent": d["agent"],
                "model": d["model"], "prompt_file": None, "out_file": d["out_file"], "workstream": d["ws"],
                "axis": d["axis"], "cwd": None, "_specs": specs}
    return {"action": "dispatch_many", "phase": st["state"], "iteration": st["iteration"],
            "dispatches": [dict(_public(s), prompt_file=None, cwd=None) for s in specs], "_specs": specs}


def _done(root, rdir, st):
    rel = lambda p: os.path.relpath(p, root)
    d = {"action": "done", "status": st["state"], "cause": st.get("block_cause"), "run_id": st["run_id"],
         "iterations": st["iteration"], "mode": st.get("mode"), "lite": st.get("lite"),
         "files_changed": len(gitutil.changed_files(root, st.get("base_ref")))}
    if st.get("review_phase_dirs"):
        d["report"] = os.path.join(st["review_phase_dirs"][-1], "review.md")
    if st.get("verified_coverage") is not None:
        d["coverage"] = st["verified_coverage"]
    if st["state"] == "BLOCKED":
        d["blocked_md"] = rel(os.path.join(rdir, "BLOCKED.md"))
    if st["state"] == "COMPLETE" and st.get("review_only"):
        d["verdict"] = st.get("review_verdict", "PASS")
        v = S.read_json(os.path.join(root, st["review_phase_dirs"][-1], "verdict.json")) if st.get("review_phase_dirs") else None
        if v:
            d["blockers"] = len(v.get("blockers", [])); d["majors"] = len(v.get("majors", []))
            d["feedback"] = rel(os.path.join(rdir, "feedback.md")) if d["blockers"] else None
    elif st["state"] == "COMPLETE":
        d["suggested_commit"] = "feat: %s" % st["task"].splitlines()[0][:60]
        d["wiki_offer"] = True
    return d


# --- mutating: prepare dispatches --------------------------------------------

def dispatch(root, run_id, cfg):
    """Render prompts for every needed spec, register them pending, return the action. Idempotent."""
    rdir = S.run_dir(root, run_id)
    with S.locked(rdir):
        st = S.load_state(rdir)
        act = next_action(root, run_id, cfg)
        specs = act.pop("_specs", None)
        if act["action"] not in ("dispatch", "dispatch_many") or not specs:
            return act
        rendered = []
        for sp in specs:
            pd = sp["phase_dir_abs"]
            os.makedirs(os.path.join(pd, "logs"), exist_ok=True)
            of = os.path.join(pd, "out.json")
            if os.path.isfile(of):
                os.unlink(of)
            pf = _render_prompt(root, st, cfg, sp)
            entry = {"phase": sp["phase"], "schema_phase": sp["schema_phase"], "agent": sp["agent"],
                     "ws": sp["ws"], "axis": sp["axis"], "iteration": st["iteration"],
                     "out_file": sp["out_file"], "phase_dir": os.path.relpath(pd, root), "dispatched_at": S.now()}
            st["pending"].append(entry)
            if sp["phase"] in ("IMPLEMENT", "TEST") and sp["ws"]:
                _ws(st, sp["ws"])["impl" if sp["phase"] == "IMPLEMENT" else "test"] = "dispatched"
            elif sp["phase"] in ("IMPLEMENT", "TEST"):
                st["workstreams"][0]["impl" if sp["phase"] == "IMPLEMENT" else "test"] = "dispatched"
            elif sp["phase"] == "SPECIALIST":
                st["specialists"][sp["axis"]] = "dispatched"
            S.append_event(rdir, "dispatch", phase=sp["phase"], iteration=st["iteration"],
                           data={"agent": sp["agent"], "model": sp["model"], "phase_dir": entry["phase_dir"],
                                 "workstream": sp["ws"], "axis": sp["axis"]})
            _count_session_dispatch(root, st)
            rendered.append({"phase": sp["phase"], "iteration": st["iteration"], "agent": sp["agent"], "model": sp["model"],
                             "prompt_file": os.path.relpath(pf, root), "out_file": sp["out_file"],
                             "workstream": sp["ws"], "axis": sp["axis"], "cwd": None})
        S.save_state(rdir, st)
    if len(rendered) == 1:
        return dict(rendered[0], action="dispatch")
    return {"action": "dispatch_many", "phase": st["state"], "iteration": st["iteration"], "dispatches": rendered}


# --- gates children ------------------------------------------------------------

def _spawn_gates(root, rdir, st, pd, ws=None, phase=None):
    gf = gates.gates_file(rdir, pd)
    if os.path.isfile(gf):
        os.unlink(gf)
    os.makedirs(os.path.join(pd, "logs"), exist_ok=True)
    log = open(os.path.join(pd, "logs", "gates.log"), "a")
    p = subprocess.Popen([sys.executable, HS_BIN, "_gates", os.path.relpath(pd, root)], cwd=root,
                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    st.setdefault("gates", {})[os.path.basename(pd)] = {"pid": p.pid, "file": os.path.relpath(gf, rdir),
                                                        "started_at": S.now(), "ws": ws, "phase": phase or st["state"]}


def _pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# --- mutating: consume outputs, process gates, transition ---------------------

def advance(root, run_id, cfg):
    rdir = S.run_dir(root, run_id)
    with S.locked(rdir):
        st = S.load_state(rdir)
        if st["state"] in TERMINAL:
            return _done(root, rdir, st)
        # 1. finished gate children
        for key, g in list(st.get("gates", {}).items()):
            gf = os.path.join(rdir, g["file"])
            if os.path.isfile(gf):
                result = S.read_json(gf)
                del st["gates"][key]
                S.commit(rdir, st, "gates.done", phase=g.get("phase"), iteration=st["iteration"],
                         data={"ok": result.get("ok"), "gate": result.get("gate"), "workstream": g.get("ws")})
                act = _after_gates(root, rdir, st, cfg, key, g, result)
                if act is not None:
                    return act
                # _after_gates mutates workstream status in memory; persist it even when no
                # transition follows (a lone gate in a dependency wave) or the ws strands at "dispatched"
                S.save_state(rdir, st)
            elif not _pid_alive(g.get("pid")):
                _spawn_gates(root, rdir, st, os.path.join(rdir, key), ws=g.get("ws"), phase=g.get("phase"))
                S.commit(rdir, st, "gates.start", phase=g.get("phase"), iteration=st["iteration"], data={"respawn": True})
        if st.get("gates"):
            return next_action(root, run_id, cfg)
        # 2. pending agent outputs
        # A `consume` event whose follow-up state write never landed (crash between the two) must be
        # replayed: the event alone proves nothing was transitioned. Dedup by "a later event for the
        # same phase_dir exists" instead of by the consume event itself.
        evs = S.read_events(rdir)
        last_dispatch = {}
        for i, ev in enumerate(evs):
            if ev.get("event") == "dispatch":
                last_dispatch[ev.get("data", {}).get("phase_dir")] = i
        settled = set()
        for i, ev in enumerate(evs):
            if ev.get("event") == "consume":
                pdn = ev.get("data", {}).get("phase_dir")
                if i < last_dispatch.get(pdn, -1):
                    continue  # re-dispatched into this phase dir since: that consume is history, not this output
                if any(e.get("data", {}).get("phase_dir") == pdn or e.get("event") in ("transition", "gates.start", "review", "block")
                       for e in evs[i + 1:]):
                    settled.add(pdn)
        for p in list(st.get("pending", [])):
            of = os.path.join(root, p["out_file"])
            if not os.path.isfile(of):
                continue
            st["pending"].remove(p)
            if p["phase_dir"] in settled:
                continue
            try:
                out = S.read_json(of)
                errs = schemas.check(p["schema_phase"], out, st, workstream=p.get("ws")) if out is not None else ["out.json empty"]
            except ValueError as e:
                out, errs = None, ["out.json is not valid JSON: %s" % e]
            if errs:
                act = _validation_fail(root, rdir, st, cfg, p, errs)
                if act is not None:
                    return act
                continue
            S.commit(rdir, st, "consume", phase=p["phase"], iteration=st["iteration"],
                     data={"phase_dir": p["phase_dir"], "workstream": p.get("ws"), "axis": p.get("axis")})
            st["validation_retry"] = 0
            act = _consume(root, rdir, st, cfg, p, out)
            if act is not None:
                return act
        if st.get("pending") or st.get("gates"):
            S.save_state(rdir, st)
            return next_action(root, run_id, cfg)
        # 3. internal transitions
        _heal(rdir, st)
        act = _step(root, rdir, st, cfg)
        if act is not None:
            return act
        S.save_state(rdir, st)
    return next_action(root, run_id, cfg)


def _normalize_out(out):
    """Agents sometimes fill optional fields with '' / {} / '(none)' instead of null; treat those as absent."""
    gap = out.get("ownership_gap")
    if isinstance(gap, dict) and not (gap.get("file") or "").strip():
        out["ownership_gap"] = None
    dc = out.get("design_conflict")
    if isinstance(dc, str) and not dc.strip():
        out["design_conflict"] = None
    if out.get("workstream") in ("", "(none)", "null", "None"):
        out["workstream"] = None
    return out


def _heal(rdir, st):
    """A workstream/specialist left at 'dispatched' with no pending entry and no gate is stranded
    (driver restarted mid-wave, or an old bug); put it back to 'pending' so _needed() re-dispatches."""
    pend = {(p["phase"], p.get("ws"), p.get("axis")) for p in st.get("pending", [])}
    gate_ws = {(g.get("phase"), g.get("ws")) for g in (st.get("gates") or {}).values()}
    single = st.get("mode") == "single"
    fixed = []
    for w in st.get("workstreams", []):
        ws = None if single else w["name"]
        for phase, key in (("IMPLEMENT", "impl"), ("TEST", "test")):
            if w.get(key) == "dispatched" and (phase, ws, None) not in pend and (phase, ws) not in gate_ws:
                w[key] = "pending"
                fixed.append("%s:%s" % (phase, w["name"]))
    for axis, stt in (st.get("specialists") or {}).items():
        if stt == "dispatched" and ("SPECIALIST", None, axis) not in pend:
            st["specialists"][axis] = "pending"
            fixed.append("SPECIALIST:" + axis)
    if fixed:
        S.append_event(rdir, "heal", phase=st["state"], iteration=st["iteration"], data={"reset": fixed})


def _consume(root, rdir, st, cfg, p, out):
    phase = p["phase"]
    pd = os.path.join(root, p["phase_dir"])
    _normalize_out(out)
    if phase == "ARCHITECT":
        return _after_architect(root, rdir, st, cfg, out, pd)
    if phase == "IMPLEMENT":
        name = p.get("ws") or st["workstreams"][0]["name"]
        if out.get("ownership_gap") or out.get("design_conflict"):
            return _route_architect_from_impl(root, rdir, st, cfg, out, name)
        st["impl_phase_dirs"].append(p["phase_dir"])
        key = p.get("ws") or name  # single mode: key by the lone workstream's name
        st.setdefault("ws_impl_files", {}).setdefault(key, [])
        st["ws_impl_files"][key] = sorted(set(st["ws_impl_files"][key]) | set(out.get("files", [])))
        if st["mode"] == "single":
            bad = _unowned(root, st, out.get("files", []), st["workstreams"][0])
            if bad:
                st["workstreams"][0]["impl"] = "pending"
                return _route_architect_from_impl(root, rdir, st, cfg, {"ownership_gap": {"file": bad[0], "reason": "implementer changed a file outside owned_files"}}, name)
        _spawn_gates(root, rdir, st, pd, ws=p.get("ws"), phase="IMPLEMENT")
        S.commit(rdir, st, "gates.start", phase="IMPLEMENT", iteration=st["iteration"], data={"phase_dir": p["phase_dir"], "workstream": p.get("ws")})
        return None
    if phase == "TEST":
        st["test_phase_dirs"].append(p["phase_dir"])
        _spawn_gates(root, rdir, st, pd, ws=p.get("ws"), phase="TEST")
        S.commit(rdir, st, "gates.start", phase="TEST", iteration=st["iteration"], data={"phase_dir": p["phase_dir"], "workstream": p.get("ws")})
        return None
    if phase == "SPECIALIST":
        st["specialists"][p["axis"]] = "done"
        st["specialist_reports"].append(os.path.join(p["phase_dir"], out.get("report", p["axis"] + ".md")))
        return None
    if phase == "INNER_FIX":
        st.setdefault("inner_done", []).append(p["agent"])
        # keep the agent's out.json for the FIX gate, write the synthetic FIX marker
        S.atomic_write_json(os.path.join(pd, "agent-out.json"), out)
        S.atomic_write_json(os.path.join(pd, "out.json"), {"phase": "FIX", "agent": p["agent"], "workstream": None})
        if p["agent"] == "implementer":
            key = st["workstreams"][0]["name"] if len(st["workstreams"]) == 1 else "fix"
            st["ws_impl_files"].setdefault(key, [])
            st["ws_impl_files"][key] = sorted(set(st["ws_impl_files"][key]) | set(out.get("files", [])))
        if p["agent"] == "tester":
            st["test_phase_dirs"].append(p["phase_dir"])
        remaining = [a for a in st.get("inner_order", []) if a not in st.get("inner_done", [])]
        if remaining:
            return None  # next fix agent dispatches via _needed
        _spawn_gates(root, rdir, st, pd, phase="FIX")
        S.commit(rdir, st, "gates.start", phase="FIX", iteration=st["iteration"], data={"phase_dir": p["phase_dir"], "inner_pass": st["inner_pass"]})
        return None
    if phase == "REVIEW":
        st["review_phase_dirs"].append(p["phase_dir"])
        return _after_review(root, rdir, st, cfg, out, pd)
    return None


def _unowned(root, st, files, w):
    import fnmatch
    globs = list(w.get("owned", [])) + list((st.get("test_owned") or {}).get(w["name"], []))
    return [f for f in files if not any(fnmatch.fnmatch(f, g) or f == g for g in globs)]


def _validation_fail(root, rdir, st, cfg, p, errs):
    st["validation_retry"] = st.get("validation_retry", 0) + 1
    if st["validation_retry"] > cfg["validation_retries"]:
        return _block(root, rdir, st, "validation", "out.json for %s failed validation %d times: %s"
                      % (p["phase"], st["validation_retry"], "; ".join(errs)))
    S.commit(rdir, st, "validate", phase=p["phase"], iteration=st["iteration"],
             data={"ok": False, "errors": errs, "retry": st["validation_retry"], "workstream": p.get("ws")})
    # next -r<n> after whatever suffix the dir already carries (gate/gap retries also use -r)
    m = re.search(r"-r(\d+)$", p["phase_dir"])
    base = re.sub(r"-r\d+$", "", p["phase_dir"])
    pd = os.path.join(root, "%s-r%d" % (base, (int(m.group(1)) if m else 0) + 1))
    os.makedirs(os.path.join(pd, "logs"), exist_ok=True)
    spec = {"phase": p["phase"], "agent": p["agent"], "ws": p.get("ws"), "axis": p.get("axis"),
            "schema_phase": p["schema_phase"], "model": _model_for(st, cfg, p["agent"]), "phase_dir_abs": pd,
            "out_file": os.path.relpath(os.path.join(pd, "out.json"), root)}
    pf = _render_prompt(root, st, cfg, spec)
    with open(pf, "a") as f:
        f.write("\n\n## Retry — previous out.json rejected\n" + "\n".join("- " + e for e in errs) + "\n")
    st["pending"].append({"phase": p["phase"], "schema_phase": p["schema_phase"], "agent": p["agent"], "ws": p.get("ws"),
                          "axis": p.get("axis"), "iteration": st["iteration"], "out_file": spec["out_file"],
                          "phase_dir": os.path.relpath(pd, root), "dispatched_at": S.now()})
    S.commit(rdir, st, "dispatch", phase=p["phase"], iteration=st["iteration"],
             data={"agent": p["agent"], "retry_reason": errs, "phase_dir": os.path.relpath(pd, root)})
    # a retry is a fresh dispatch the driver must send now, not something to wait on
    return {"action": "dispatch", "phase": p["phase"], "iteration": st["iteration"], "agent": p["agent"],
            "model": _model_for(st, cfg, p["agent"]), "prompt_file": os.path.relpath(pf, root), "out_file": spec["out_file"],
            "workstream": p.get("ws"), "axis": p.get("axis"), "cwd": None, "retry_reason": "; ".join(errs)}


def _after_architect(root, rdir, st, cfg, out, pd):
    st["size"] = out["size"]
    # an architect re-run inside the same iteration (ownership gap / design conflict) must give the
    # following IMPLEMENT/TEST fresh phase dirs: carry the run-level retry into per-ws retry counters
    base_retry = st.get("retry", 0)
    prev = {w["name"]: w for w in st.get("workstreams", [])}
    st["workstreams"] = [{"name": w["name"], "owned": w["owned"], "depends_on": w.get("depends_on") or [],
                          "ac": w["ac"], "impl": "pending", "test": "pending",
                          "retry_impl": max(prev.get(w["name"], {}).get("retry_impl", 0), base_retry),
                          "retry_test": max(prev.get(w["name"], {}).get("retry_test", 0), base_retry)}
                         for w in out["workstreams"]]
    st["untestable"] = out.get("untestable") or []
    st["test_owned"] = out.get("test_owned") or {}
    st["ac"] = out["ac"]
    design_src = os.path.join(pd, out["design"])
    if os.path.isfile(design_src):
        with open(design_src) as f:
            S.atomic_write(os.path.join(rdir, "design.md"), f.read())
    if not st.get("lite") and out["size"] == "S" and cfg["lite"]["auto"] and not st.get("lite_forced"):
        st["lite"] = True
        st["cap"] = min(st["cap"], cfg["lite"]["cap"])
    if st.get("lite") or len(st["workstreams"]) == 1 or cfg.get("no_parallel"):
        if len(st["workstreams"]) > 1:
            owned = [p for w in st["workstreams"] for p in w["owned"]]
            ac = [a for w in st["workstreams"] for a in w["ac"]]
            to = {k: v for k, v in st["test_owned"].items()}
            st["workstreams"] = [{"name": "all", "owned": owned, "depends_on": [], "ac": ac, "impl": "pending", "test": "pending",
                                  "retry_impl": base_retry, "retry_test": base_retry}]
            st["test_owned"] = {"all": [g for v in to.values() for g in v]}
        st["mode"] = "single"
    else:
        st["mode"] = "parallel"
    st["state"] = "IMPLEMENT"
    S.commit(rdir, st, "transition", phase="IMPLEMENT", iteration=st["iteration"],
             data={"from": "ARCHITECT", "mode": st["mode"], "lite": st.get("lite"), "workstreams": [w["name"] for w in st["workstreams"]]})
    return None


def _route_architect_from_impl(root, rdir, st, cfg, out, ws_name):
    gap = out.get("ownership_gap")
    reason = ("ownership gap in %s: %s (%s)" % (ws_name, gap["file"], gap["reason"])) if gap else ("design conflict in %s: %s" % (ws_name, out.get("design_conflict")))
    st["gap_count"] = st.get("gap_count", 0) + 1
    S.atomic_write(os.path.join(rdir, "feedback.md"), "# Feedback for architecter\n\n## Implementer stopped\n%s\n\nUpdate the ownership map / design and re-signal.\n" % reason)
    if st["gap_count"] > 1:
        st["iteration"] += 1
        if st["iteration"] > st["cap"]:
            return _block(root, rdir, st, "convergence", "cap exceeded after repeated " + reason)
    st["pending"] = []
    for w in st["workstreams"]:
        w["impl"] = "pending"; w["test"] = "pending"
    st["state"] = "ARCHITECT"
    st["retry"] = st.get("retry", 0) + 1 if st["gap_count"] > 1 else 1
    S.commit(rdir, st, "transition", phase="ARCHITECT", iteration=st["iteration"], data={"from": "IMPLEMENT", "reason": reason[:160]})
    return None


def _after_gates(root, rdir, st, cfg, key, g, result):
    phase = g.get("phase")
    ws = g.get("ws")
    w = _ws(st, ws) if ws else (st["workstreams"][0] if st.get("workstreams") else None)
    if phase == "IMPLEMENT":
        if result.get("ok"):
            if w:
                w["impl"] = "done"; w["retry_impl"] = 0
            st["gate_retry"] = 0
            return None
        return _gate_fail(root, rdir, st, cfg, phase, result, w, "impl")
    if phase == "TEST":
        cov = result.get("coverage") or {}
        if st.get("review_only"):
            # nothing to re-dispatch: a red suite or unparseable coverage is simply reported to the reviewer
            if w:
                w["test"] = "done"
            _merge_test_gate(st, result)
            return None
        if cov.get("status") == "unparseable":
            return _gate_fail(root, rdir, st, cfg, phase, result, w, "test")
        if result.get("tests") == "fail":
            to = S.read_json(os.path.join(root, key if os.path.isabs(key) else os.path.join(rdir, key), "out.json")) or {}
            if not to.get("findings"):
                return _gate_fail(root, rdir, st, cfg, phase, result, w, "test")
        if w:
            w["test"] = "done"; w["retry_test"] = 0
        st["gate_retry"] = 0
        _merge_test_gate(st, result)
        return None
    if phase == "CONFLICT":
        if result.get("ok"):
            st["state"] = "RISK"
            S.commit(rdir, st, "transition", phase="RISK", iteration=st["iteration"], data={"from": "CONFLICT"})
            return None
        tail = next((c.get("tail", "")[-800:] for c in result.get("cmds", []) if c.get("exit") != 0), "")
        return _conflict_fail(root, rdir, st, cfg, [{"file": "-", "owners": [], "reason": "integration build/test failed"}], tail)
    if phase == "FIX":
        vr = result.get("verify") or {}
        failed = sorted(k for k, v in vr.items() if v == "fail")
        if result.get("ok") and not failed:
            _merge_test_gate(st, result)
            st["delta"] = True
            st["state"] = "REVIEW"
            S.commit(rdir, st, "transition", phase="REVIEW", iteration=st["iteration"], data={"from": "INNER_FIX", "mode": "delta", "verify": vr})
            return None
        return _inner_retry(root, rdir, st, cfg, "verify failed: %s" % (failed or "build/test"), result)
    return None


def _merge_test_gate(st, result):
    """Fold one TEST/FIX gate result into `last_test_gate`.

    Results from a *previous* iteration are discarded (a fixed suite must clear a stale `fail`);
    within one iteration, per-workstream results merge so the verdict sees every workstream.
    """
    prev = st.get("last_test_gate") or {}
    if prev.get("iteration") != st["iteration"]:
        prev = {}
    cov = dict(result.get("coverage") or {})
    pc = dict((prev.get("coverage") or {}).get("per_file") or {})
    pc.update(cov.get("per_file") or {})
    cov["per_file"] = pc
    cov["unverified"] = sorted(set((prev.get("coverage") or {}).get("unverified") or []) | set(cov.get("unverified") or []))
    rows = {r["test"]: r for r in ((prev.get("redgreen") or {}).get("rows") or [])}
    rg = result.get("redgreen") or {}
    for r in rg.get("rows") or []:
        rows[r["test"]] = r
    both = (prev.get("tests"), result.get("tests"))
    tests = next((t for t in ("fail", "pre-existing") if t in both), "pass")
    st["last_test_gate"] = {"iteration": st["iteration"], "tests": tests, "coverage": cov,
                            "tests_new": sorted(set(prev.get("tests_new") or []) | set(result.get("tests_new") or [])),
                            "tests_pre": sorted(set(prev.get("tests_pre") or []) | set(result.get("tests_pre") or [])),
                            "redgreen": {"ref": rg.get("ref") or (prev.get("redgreen") or {}).get("ref"), "rows": list(rows.values())}}
    st["verified_coverage"] = cov.get("total")


def _gate_fail(root, rdir, st, cfg, phase, result, w, key):
    st["gate_retry"] = st.get("gate_retry", 0) + 1
    tail = ""
    for c in result.get("cmds", []):
        if c.get("exit") != 0:
            tail = "`%s` exit %s\n```\n%s\n```" % (c["cmd"], c["exit"], (c.get("tail") or "")[-800:])
            break
    if (result.get("coverage") or {}).get("status") == "unparseable":
        tail = tail or "coverage report `%s` could not be parsed" % result["coverage"].get("report")
    S.append_event(rdir, "gate.%s" % result.get("gate"), phase=phase, iteration=st["iteration"],
                   data={"ok": False, "retry": st["gate_retry"], "workstream": w["name"] if w else None})
    if st["gate_retry"] > cfg["gate_retries"]:
        return _block(root, rdir, st, "gate", "%s gate failed %d times.\n\n%s" % (phase, st["gate_retry"], tail))
    S.atomic_write(os.path.join(rdir, "feedback.md"), "# Feedback for %s (gate retry %d)\n\n## Gate failure\n%s\n" % (phase, st["gate_retry"], tail))
    if w:
        w[key] = "pending"
        w["retry_" + key] = w.get("retry_" + key, 0) + 1
    S.save_state(rdir, st)
    return None


def _conflict_fail(root, rdir, st, cfg, violations, tail=""):
    S.atomic_write_json(os.path.join(rdir, "conflict.json"), {"ok": False, "violations": violations, "iteration": st["iteration"]})
    lines = ["# Feedback for architecter (CONFLICT)", "", "## Ownership / integration violations"]
    for v in violations:
        lines.append("- %s — %s (owners: %s)" % (v["file"], v["reason"], ", ".join(v["owners"]) or "none"))
    if tail:
        lines += ["", "```", tail, "```"]
    S.atomic_write(os.path.join(rdir, "feedback.md"), "\n".join(lines) + "\n")
    S.append_event(rdir, "gate.conflict", phase="CONFLICT", iteration=st["iteration"], data={"ok": False, "violations": len(violations)})
    st["iteration"] += 1
    if st["iteration"] > st["cap"]:
        return _block(root, rdir, st, "convergence", "cap exceeded after CONFLICT")
    st["arch_iterations"].append(st["iteration"])
    for w in st["workstreams"]:
        w["impl"] = "pending"; w["test"] = "pending"
    st["state"] = "ARCHITECT"
    st["retry"] = 0
    S.commit(rdir, st, "transition", phase="ARCHITECT", iteration=st["iteration"], data={"from": "CONFLICT"})
    return None


def _step(root, rdir, st, cfg):
    """Internal transitions that need no agent. Loops until an agent or gate is needed."""
    while True:
        phase = st["state"]
        if phase == "IMPLEMENT":
            if all(w.get("impl") == "done" for w in st["workstreams"]):
                st["state"] = "TEST"
                S.commit(rdir, st, "transition", phase="TEST", iteration=st["iteration"], data={"from": "IMPLEMENT"})
                continue
            return None
        if phase == "TEST":
            if all(w.get("test") == "done" for w in st["workstreams"]):
                st["state"] = "CONFLICT"
                S.commit(rdir, st, "transition", phase="CONFLICT", iteration=st["iteration"], data={"from": "TEST"})
                continue
            return None
        if phase == "CONFLICT":
            if st["mode"] != "parallel":
                S.atomic_write_json(os.path.join(rdir, "conflict.json"), {"ok": True, "skipped": "single"})
                st["state"] = "RISK"
                S.commit(rdir, st, "transition", phase="RISK", iteration=st["iteration"], data={"from": "CONFLICT", "skipped": True})
                continue
            changed = gitutil.changed_files(root, st.get("base_ref"))
            viol = gates.ownership_check(root, changed, st["workstreams"], st.get("test_owned"), cfg.get("generated"))
            if viol:
                return _conflict_fail(root, rdir, st, cfg, viol)
            pd = os.path.join(rdir, phase_dir_name("CONFLICT", st["iteration"]))
            os.makedirs(os.path.join(pd, "logs"), exist_ok=True)
            S.atomic_write_json(os.path.join(pd, "out.json"), {"phase": "CONFLICT"})
            S.atomic_write_json(os.path.join(rdir, "conflict.json"), {"ok": None, "violations": [], "integration": "running"})
            _spawn_gates(root, rdir, st, pd, phase="CONFLICT")
            S.commit(rdir, st, "gates.start", phase="CONFLICT", iteration=st["iteration"], data={"phase_dir": os.path.relpath(pd, root)})
            return None
        if phase == "RISK":
            mode = "single" if (st.get("lite") or st["review_mode"] == "single") else st["review_mode"]
            if mode == "single":
                st["risk"] = {"axes": [], "matches": [], "skipped": "single"}
                st["specialists"] = {}
            elif mode == "split":
                st["risk"] = {"axes": ["sec", "perf"], "matches": [], "mode": "split"}
                st["specialists"] = {"sec": "pending", "perf": "pending"}
            else:
                rk = R.detect(root, st.get("base_ref"))
                st["risk"] = rk
                st["specialists"] = {a: "pending" for a in rk["axes"]}
            S.atomic_write_json(os.path.join(rdir, "risk.json"), st["risk"])
            S.append_event(rdir, "risk", phase="RISK", iteration=st["iteration"], data={"axes": list(st["specialists"].keys())})
            st["specialist_reports"] = []
            st["state"] = "SPECIALISTS" if st["specialists"] else "REVIEW"
            S.commit(rdir, st, "transition", phase=st["state"], iteration=st["iteration"], data={"from": "RISK"})
            continue
        if phase == "SPECIALISTS":
            if all(v == "done" for v in st["specialists"].values()):
                st["state"] = "REVIEW"
                S.commit(rdir, st, "transition", phase="REVIEW", iteration=st["iteration"], data={"from": "SPECIALISTS"})
                continue
            return None
        return None


# --- review -----------------------------------------------------------------

def _after_review(root, rdir, st, cfg, out, pd):
    tg = st.get("last_test_gate") or {}
    impl_files = sorted({f for lst in (st.get("ws_impl_files") or {}).values() for f in lst})
    cur_new = []
    for d in st.get("test_phase_dirs", [])[-max(1, len(st["workstreams"])):]:
        o = S.read_json(os.path.join(root, d, "out.json")) or {}
        if o.get("phase") == "FIX":
            o = S.read_json(os.path.join(root, d, "agent-out.json")) or {}
        cur_new.extend(o.get("new_tests", []))
    proven = set(st.get("proven", []))
    need = [t for t in cur_new if t not in proven]
    proof_ref = st.get("proof_ref") or st.get("base_ref")
    # specialist blockers are unioned unless the chief overrode them by id
    overrides = {o["id"] for o in out.get("overrides") or []}
    merged = dict(out)
    merged["findings"] = list(out.get("findings", []))
    for rep in st.get("specialist_reports") or []:
        so = S.read_json(os.path.join(root, os.path.dirname(rep), "out.json")) or {}
        for f in so.get("findings", []):
            if f["severity"] == "blocker" and f["id"] not in overrides:
                merged["findings"].append(dict(f, tag=so["axis"].upper(), route="implementer", verify="manual",
                                               source=so["axis"], prior_id=None))
    blockers, majors, route = verdict(merged, tg, st.get("coverage_threshold"), impl_files, need, proof_ref)
    rg = tg.get("redgreen") or {}
    if _same_ref(rg.get("ref"), proof_ref):
        for r in rg.get("rows", []):
            if r.get("kind") in ("assertion", "compile") and r.get("test") not in proven:
                st.setdefault("proven", []).append(r["test"])
    was_delta = bool(st.get("delta"))
    st["delta"] = False
    S.atomic_write_json(os.path.join(pd, "verdict.json"),
                        {"verdict": "FAIL" if blockers else "PASS", "route": route, "delta": was_delta, "blockers": blockers, "majors": majors})
    S.append_event(rdir, "review", phase="REVIEW", iteration=st["iteration"],
                   data={"verdict": "FAIL" if blockers else "PASS", "route": route, "delta": was_delta,
                         "blockers": len(blockers), "majors": len(majors)})
    if not blockers:
        st["state"] = "COMPLETE"
        S.commit(rdir, st, "complete", phase="REVIEW", iteration=st["iteration"], data={})
        gitutil.delete_refs(root, st["run_id"])
        return _done(root, rdir, st)
    if st.get("review_only"):
        # a review-only run never routes: FAIL is the answer, with the findings on disk
        _write_feedback(rdir, st, blockers, majors, route)
        st["state"] = "COMPLETE"
        st["review_verdict"] = "FAIL"
        S.commit(rdir, st, "complete", phase="REVIEW", iteration=st["iteration"],
                 data={"review_only": True, "verdict": "FAIL", "blockers": len(blockers)})
        return _done(root, rdir, st)
    # convergence (spec §8.3) — only reviewer findings are tracked; gate blockers (G-*) are
    # mechanical and self-clearing, so they neither count as repeats nor as "unresolved"
    before = st.get("findings", {})
    prev_had = any(v["seen"] and v["seen"][-1] == st["iteration"] - 1 for v in before.values())
    fs, forced, block, resolved, repeats, third = converge(before, blockers, st["iteration"], route,
                                                    st.get("arch_iterations", []), st.get("zero_progress", 0))
    st["findings"] = fs
    st["zero_progress"] = st["zero_progress"] + 1 if (resolved == 0 and prev_had) else 0
    S.append_event(rdir, "convergence", phase="REVIEW", iteration=st["iteration"],
                   data={"resolved": resolved, "repeats": repeats, "forced": forced, "block": block})
    if block:
        _write_feedback(rdir, st, blockers, majors, route)
        return _block(root, rdir, st, "convergence", block)
    esc_model = (cfg.get("escalation") or {}).get("model")
    if esc_model and forced == "architecter" and not block and not st.get("escalated") and route in ("implementer", "tester"):
        # spec §8.6: the first time convergence would take the blocker away from the agent that failed it
        # (repeat / zero-progress → architecter), spend one borrowed attempt on a stronger model for that
        # same agent instead. Once. Convergence resumes normally on the next review.
        repeated = [fs[k]["id"] for k in fs if len(fs[k]["seen"]) >= 2 and fs[k]["seen"][-1] == st["iteration"]]
        st["escalated"] = True
        st["escalation"] = {"model": esc_model, "iteration": st["iteration"] + 1, "findings": repeated}
        S.append_event(rdir, "escalate", phase="REVIEW", iteration=st["iteration"],
                       data={"model": esc_model, "findings": repeated, "route": route, "instead_of": forced})
        forced = None
        st["zero_progress"] = 0
    if forced:
        route = forced
    _write_feedback(rdir, st, blockers, majors, route)
    # inner fix loop eligibility (spec §8.2)
    verifiable = all(b.get("verify") not in (None, "", "manual", "untrusted") for b in blockers)
    if was_delta:
        # delta FAIL: stay inner while passes remain, else fall to a full round
        if route in ("implementer", "tester") and verifiable and st["inner_pass"] + 1 < st["inner_cap"]:
            return _enter_inner(root, rdir, st, cfg, blockers, route, bump=False)
        return _full_round(root, rdir, st, cfg, route)
    if route in ("implementer", "tester") and verifiable and not st.get("lite_no_inner"):
        return _enter_inner(root, rdir, st, cfg, blockers, route, bump=True)
    return _full_round(root, rdir, st, cfg, route)


def _write_feedback(rdir, st, blockers, majors, route):
    fb = ["# Feedback for iteration %d  (target: %s)\n" % (st["iteration"] + 1, route), "## Blockers",
          "| id | tag | file:line | desc | verify |", "|---|---|---|---|---|"]
    for b in blockers:
        fb.append("| %s | %s | %s:%s | %s | `%s` |" % (b["id"], b["tag"], b.get("file"), b.get("line"), b["desc"], b.get("verify")))
    fb.append("\n## Majors (fix if cheap)")
    for m in majors:
        fb.append("- %s [%s] %s" % (m["id"], m["tag"], m["desc"]))
    S.atomic_write(os.path.join(rdir, "feedback.md"), "\n".join(fb) + "\n")


def _snapshot_iter(root, st, route):
    st["iter_ref"] = gitutil.snapshot(root, "%s/iter-%d" % (st["run_id"], st["iteration"]))
    # proof ref = snapshot before the last CODE change; a tester-only round changes no code
    if route in ("implementer", "architecter"):
        st["proof_ref"] = st["iter_ref"]


def _enter_inner(root, rdir, st, cfg, blockers, route, bump):
    if bump:
        st["iteration"] += 1
        if st["iteration"] > st["cap"]:
            return _block(root, rdir, st, "convergence", "iteration cap %d exceeded; last route %s" % (st["cap"], route))
        st["inner_pass"] = 0
    else:
        st["inner_pass"] += 1
    _snapshot_iter(root, st, route)
    agents = []
    if any(b["route"] == "implementer" for b in blockers):
        agents.append("implementer")
    if any(b["route"] == "tester" for b in blockers):
        agents.append("tester")
    st["inner_order"] = agents or [route]
    st["inner_done"] = []
    st["inner_verify"] = {b["id"]: b.get("verify") for b in blockers}
    st["state"] = "INNER_FIX"
    st["retry"] = 0
    S.commit(rdir, st, "transition", phase="INNER_FIX", iteration=st["iteration"],
             data={"from": "REVIEW", "route": route, "inner_pass": st["inner_pass"], "agents": st["inner_order"]})
    return None


def _inner_retry(root, rdir, st, cfg, reason, result):
    """Verify/build/test failed after a fix pass."""
    S.append_event(rdir, "verify", phase="INNER_FIX", iteration=st["iteration"], data={"ok": False, "reason": reason[:160], "inner_pass": st["inner_pass"]})
    fb = open(os.path.join(rdir, "feedback.md")).read() if os.path.isfile(os.path.join(rdir, "feedback.md")) else ""
    fails = {k: v for k, v in (result.get("verify") or {}).items() if v == "fail"}
    tail = next((c.get("tail", "")[-600:] for c in result.get("cmds", []) if c.get("exit") != 0), "")
    S.atomic_write(os.path.join(rdir, "feedback.md"), fb + "\n## Failing checks (inner pass %d)\n%s\n%s\n" % (
        st["inner_pass"], "\n".join("- %s: verify still fails" % k for k in fails) or "- build/test failed", ("```\n%s\n```" % tail) if tail else ""))
    # inner_cap = max fix passes per review round: passes are numbered 0..inner_cap-1
    if st["inner_pass"] + 1 < st["inner_cap"]:
        st["inner_pass"] += 1
        st["inner_done"] = []
        st["state"] = "INNER_FIX"
        S.commit(rdir, st, "transition", phase="INNER_FIX", iteration=st["iteration"], data={"from": "INNER_FIX", "inner_pass": st["inner_pass"], "reason": reason[:120]})
        return None
    route = "implementer" if "implementer" in (st.get("inner_order") or []) else "tester"
    return _full_round(root, rdir, st, cfg, route, bump=True)


def _full_round(root, rdir, st, cfg, route, bump=True):
    if bump:
        st["iteration"] += 1
        if st["iteration"] > st["cap"]:
            return _block(root, rdir, st, "convergence", "iteration cap %d exceeded; last route %s" % (st["cap"], route))
    _snapshot_iter(root, st, route)
    st["inner_pass"] = 0
    st["inner_order"] = []
    st["inner_done"] = []
    st["delta"] = False
    if route == "architecter":
        st["arch_iterations"].append(st["iteration"])
        for w in st["workstreams"]:
            w["impl"] = "pending"; w["test"] = "pending"
        st["state"] = "ARCHITECT"
    elif route == "implementer":
        for w in st["workstreams"]:
            w["impl"] = "pending"; w["test"] = "pending"
        st["state"] = "IMPLEMENT"
    else:
        for w in st["workstreams"]:
            w["test"] = "pending"
        st["state"] = "TEST"
    st["retry"] = 0
    S.commit(rdir, st, "transition", phase=st["state"], iteration=st["iteration"], data={"from": "REVIEW", "route": route})
    return None


def _block(root, rdir, st, cause, reason):
    st["state"] = "BLOCKED"
    st["block_cause"] = cause
    st["pending"] = []
    st["gates"] = {}
    events = S.read_events(rdir)
    lines = ["# BLOCKED — run %s" % st["run_id"], "", "Cause: **%s**" % cause, "", reason, "", "## Task", st["task"], ""]
    if st.get("findings"):
        lines += ["## Convergence", "| finding | seen in iterations | routes |", "|---|---|---|"]
        for fp, v in st["findings"].items():
            lines.append("| %s | %s | %s |" % (v["id"], v["seen"], ", ".join(v["routes"])))
        lines.append("")
    lines += ["## Timeline", "| ts | event | phase | iteration | data |", "|---|---|---|---|---|"]
    for e in events:
        lines.append("| %s | %s | %s | %s | %s |" % (e.get("ts"), e.get("event"), e.get("phase", ""), e.get("iteration", ""),
                                                   str(e.get("data", ""))[:120].replace("|", "/")))
    S.atomic_write(os.path.join(rdir, "BLOCKED.md"), "\n".join(lines) + "\n")
    S.commit(rdir, st, "block", phase=st["state"], iteration=st["iteration"], data={"cause": cause, "reason": reason[:200]})
    return _done(root, rdir, st)


def block_manual(root, run_id, cfg, cause, reason):
    rdir = S.run_dir(root, run_id)
    with S.locked(rdir):
        st = S.load_state(rdir)
        return _block(root, rdir, st, cause, reason)


def answer(root, run_id, cfg, key, value):
    """Record an answer to an `ask` action (no asks are emitted in P1a; kept for driver symmetry)."""
    rdir = S.run_dir(root, run_id)
    with S.locked(rdir):
        st = S.load_state(rdir)
        st.setdefault("answers", {})[key] = value
        S.commit(rdir, st, "answer", phase=st["state"], iteration=st["iteration"], data={"key": key, "value": value})
    return next_action(root, run_id, cfg)


# --- resume (spec §8.7) ---------------------------------------------------------

QUIET_SECS = 600  # an agent whose phase dir has not changed for this long is presumed dead


def _newest_mtime(path):
    newest = 0.0
    for dp, _, fns in os.walk(path):
        for fn in fns:
            try:
                newest = max(newest, os.path.getmtime(os.path.join(dp, fn)))
            except OSError:
                pass
    return newest


def resume(root, run_id, cfg):
    """Recover a run whose driver stopped.

    1. outputs already on disk → consumed by advance() (event `recover`)
    2. gate children: alive → wait; dead without a file → advance() respawns
    3. pending agents whose phase dir changed within QUIET_SECS → still running → wait
    4. pending agents quiet for longer → drop them so next_action re-dispatches the same phase
    """
    rdir = S.run_dir(root, run_id)
    gitutil.prune(root)
    now_ts = S.parse_ts(S.now()).timestamp()
    with S.locked(rdir):
        st = S.load_state(rdir)
        if st is None:
            return {"action": "error", "message": "no such run %s" % run_id}
        if st["state"] in TERMINAL:
            return _done(root, rdir, st)
        recovered, quiet, running = [], [], []
        for p in list(st.get("pending", [])):
            of = os.path.join(root, p["out_file"])
            if os.path.isfile(of):
                recovered.append(p["phase_dir"])
                continue
            pd = os.path.join(root, p["phase_dir"])
            touched = _newest_mtime(pd)
            since = S.parse_ts(p["dispatched_at"]).timestamp()
            age = now_ts - max(touched, since)
            if age < QUIET_SECS:
                running.append(p["phase_dir"])
            else:
                quiet.append(p["phase_dir"])
                st["pending"].remove(p)
                # the phase goes back to pending so _needed() re-dispatches it
                if p["phase"] in ("IMPLEMENT", "TEST"):
                    w = _ws(st, p.get("ws")) or (st["workstreams"][0] if st.get("workstreams") else None)
                    if w:
                        w["impl" if p["phase"] == "IMPLEMENT" else "test"] = "pending"
                elif p["phase"] == "SPECIALIST":
                    st["specialists"][p["axis"]] = "pending"
                elif p["phase"] == "INNER_FIX":
                    st["inner_done"] = [a for a in st.get("inner_done", []) if a != p["agent"]]
        S.commit(rdir, st, "resume", phase=st["state"], iteration=st["iteration"],
                 data={"recovered": recovered, "quiet": quiet, "running": running})
    if recovered:
        S.append_event(rdir, "recover", phase=st["state"], iteration=st["iteration"], data={"phase_dirs": recovered})
    return advance(root, run_id, cfg)
