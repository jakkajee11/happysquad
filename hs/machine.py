"""State machine (spec §8) — P0 scope: single workstream, linear phases, cap, verdict truth table.

Phases: ARCHITECT -> IMPLEMENT -> TEST -> REVIEW -> COMPLETE | BLOCKED
Every mutating entry point takes the run lock. `next_action` is read-only.
"""
import os
import re
import subprocess
import sys

from . import gates, gitutil, render, schemas, state as S

AGENT_FOR = {"ARCHITECT": "architecter", "IMPLEMENT": "implementer", "TEST": "tester", "REVIEW": "reviewer"}
LINEAR = ["ARCHITECT", "IMPLEMENT", "TEST", "REVIEW"]
PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HS_BIN = os.path.join(PLUGIN_ROOT, "bin", "hs")


def slug(text, n=6):
    words = re.findall(r"[A-Za-z0-9]+", text)[:n]
    return "-".join(w.lower() for w in words) or "task"


def phase_dir_name(phase, iteration, retry=0):
    name = "%s-i%d" % (phase, iteration)
    if retry:
        name += "-r%d" % retry
    return name


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
            "mode": "single", "lite": lite, "size": None,
            "base_ref": base, "iter_ref": None, "proof_ref": base, "proven": [],
            "state": "ARCHITECT", "iteration": 1, "gate_retry": 0, "validation_retry": 0,
            "cap": cfg["lite"]["cap"] if lite else cfg["cap"],
            "coverage_threshold": cfg["coverage_threshold"],
            "cmds": {"build": cfg.get("build_cmd"), "test": cfg.get("test_cmd"), "coverage_report": cfg.get("coverage_report")},
            "workstreams": [], "untestable": [], "impl_phase_dirs": [],
            "pending": [], "gates": {}, "findings": {},
            "started_at": S.now(),
        }
        S.atomic_write(os.path.join(rdir, "task.md"), task + "\n")
        S.commit(rdir, st, "run.start", data={"base_ref": base, "lite": lite})
        S.set_current(root, run_id)
    return next_action(root, run_id, cfg)


# --- prompts -----------------------------------------------------------------

def _vars(root, st, cfg, phase, pd):
    rdir = S.run_dir(root, st["run_id"])
    rel = lambda p: os.path.relpath(p, root)
    v = {
        "hs": HS_BIN, "run_id": st["run_id"], "iteration": st["iteration"], "task": st["task"],
        "task_file": rel(os.path.join(rdir, "task.md")),
        "design_path": rel(os.path.join(rdir, "design.md")),
        "phase_dir": rel(pd), "out_file": rel(os.path.join(pd, "out.json")),
        "out_schema": schemas.render(phase),
        "base_ref": st.get("base_ref"), "iter_ref": st.get("iter_ref"),
        "proof_ref": st.get("proof_ref") or st.get("base_ref"),
        "build_cmd": st["cmds"].get("build"), "test_cmd": st["cmds"].get("test"),
        "coverage_report": st["cmds"].get("coverage_report"),
        "threshold": st["coverage_threshold"],
        "feedback_path": rel(os.path.join(rdir, "feedback.md")) if os.path.isfile(os.path.join(rdir, "feedback.md")) else None,
        "implementation_path": None, "test_report_path": None, "gates_summary": None,
        "owned_files": None, "test_owned_files": None, "ac_list": None,
    }
    ws = st.get("workstreams") or []
    if ws:
        v["owned_files"] = ws[0].get("owned")
        v["ac_list"] = ws[0].get("ac")
        v["test_owned_files"] = (st.get("test_owned") or {}).get(ws[0]["name"])
    if st.get("impl_phase_dirs"):
        v["implementation_path"] = os.path.join(st["impl_phase_dirs"][-1], "implementation.md")
    if st.get("test_phase_dirs"):
        v["test_report_path"] = os.path.join(st["test_phase_dirs"][-1], "test-report.md")
        g = S.read_json(os.path.join(rdir, "gates-%s.json" % os.path.basename(st["test_phase_dirs"][-1])))
        if g:
            cov = g.get("coverage") or {}
            v["gates_summary"] = "tests=%s coverage_status=%s coverage_total=%s per_file=%s" % (
                g.get("tests"), cov.get("status"), cov.get("total"), cov.get("per_file"))
    return v


def _render_prompt(root, st, cfg, phase, pd):
    tpl = os.path.join(PLUGIN_ROOT, "prompts", "%s.md" % phase.lower())
    text = render.render_file(tpl, _vars(root, st, cfg, phase, pd))
    rdir = S.run_dir(root, st["run_id"])
    pf = os.path.join(rdir, "prompts", os.path.basename(pd) + ".md")
    S.atomic_write(pf, text)
    return pf


# --- read-only: what should happen now ---------------------------------------

def next_action(root, run_id, cfg):
    rdir = S.run_dir(root, run_id)
    st = S.load_state(rdir)
    if st is None:
        return {"action": "error", "message": "no such run %s" % run_id}
    if st["state"] in ("COMPLETE", "BLOCKED"):
        return _done(root, rdir, st)
    # gates running / finished-but-unconsumed for this phase?
    for key, g in st.get("gates", {}).items():
        gf = os.path.join(rdir, g["file"])
        if os.path.isfile(gf):
            return {"action": "advance", "reason": "gates finished — run `hs advance`"}
        return {"action": "wait", "for": "gates", "files": [os.path.relpath(gf, root)],
                "pid": g.get("pid"), "since": g.get("started_at")}
    if st.get("pending"):
        p = st["pending"][0]
        if os.path.isfile(os.path.join(root, p["out_file"])):
            return {"action": "advance", "reason": "out.json present — run `hs advance`"}
        # already dispatched, output not yet written: return the same dispatch so a driver can
        # re-send it after an agent error; `hs wait` treats it as "poll out_file".
        pf = os.path.join(rdir, "prompts", os.path.basename(p["phase_dir"]) + ".md")
        return {"action": "dispatch", "phase": p["phase"], "iteration": p["iteration"], "agent": AGENT_FOR[p["phase"]],
                "model": cfg["models"][AGENT_FOR[p["phase"]]], "prompt_file": os.path.relpath(pf, root),
                "out_file": p["out_file"], "workstream": None, "cwd": None, "redispatch": True,
                "since": p["dispatched_at"]}
    phase = st["state"]
    pd = os.path.join(rdir, phase_dir_name(phase, st["iteration"], st.get("retry", 0)))
    return {"action": "dispatch", "phase": phase, "iteration": st["iteration"], "agent": AGENT_FOR[phase],
            "model": cfg["models"][AGENT_FOR[phase]],
            "prompt_file": None, "out_file": os.path.relpath(os.path.join(pd, "out.json"), root),
            "workstream": None, "cwd": None, "_phase_dir": pd}


def _done(root, rdir, st):
    rel = lambda p: os.path.relpath(p, root)
    d = {"action": "done", "status": st["state"], "cause": st.get("block_cause"), "run_id": st["run_id"],
         "iterations": st["iteration"], "files_changed": len(gitutil.changed_files(root, st.get("base_ref")))}
    if st.get("review_phase_dirs"):
        d["report"] = os.path.join(st["review_phase_dirs"][-1], "review.md")
    if st.get("verified_coverage") is not None:
        d["coverage"] = st["verified_coverage"]
    if st["state"] == "BLOCKED":
        d["blocked_md"] = rel(os.path.join(rdir, "BLOCKED.md"))
    if st["state"] == "COMPLETE":
        d["suggested_commit"] = "feat: %s" % st["task"].splitlines()[0][:60]
    return d


# --- mutating: prepare a dispatch --------------------------------------------

def dispatch(root, run_id, cfg):
    """Render the prompt, register pending, return the dispatch action. Idempotent while pending."""
    rdir = S.run_dir(root, run_id)
    with S.locked(rdir):
        st = S.load_state(rdir)
        act = next_action(root, run_id, cfg)
        if act["action"] != "dispatch" or act.get("redispatch"):
            return act
        pd = act.pop("_phase_dir")
        os.makedirs(os.path.join(pd, "logs"), exist_ok=True)
        of = os.path.join(pd, "out.json")
        if os.path.isfile(of):
            os.unlink(of)
        pf = _render_prompt(root, st, cfg, act["phase"], pd)
        act["prompt_file"] = os.path.relpath(pf, root)
        st["pending"] = [{"phase": act["phase"], "iteration": st["iteration"], "workstream": None,
                          "out_file": act["out_file"], "phase_dir": os.path.relpath(pd, root), "dispatched_at": S.now()}]
        S.commit(rdir, st, "dispatch", phase=act["phase"], iteration=st["iteration"],
                 data={"agent": act["agent"], "model": act["model"], "phase_dir": os.path.relpath(pd, root)})
    return act


# --- mutating: consume out.json, run gates, transition -----------------------

def _spawn_gates(root, rdir, st, pd):
    gf = gates.gates_file(rdir, pd)
    if os.path.isfile(gf):
        os.unlink(gf)
    log = open(os.path.join(pd, "logs", "gates.log"), "a")
    p = subprocess.Popen([sys.executable, HS_BIN, "_gates", os.path.relpath(pd, root)], cwd=root,
                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    st["gates"] = {os.path.basename(pd): {"pid": p.pid, "file": os.path.relpath(gf, rdir), "started_at": S.now()}}


def _pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def advance(root, run_id, cfg):
    rdir = S.run_dir(root, run_id)
    with S.locked(rdir):
        st = S.load_state(rdir)
        if st["state"] in ("COMPLETE", "BLOCKED"):
            return _done(root, rdir, st)
        # 1. gates in flight / finished?
        for key, g in list(st.get("gates", {}).items()):
            gf = os.path.join(rdir, g["file"])
            if os.path.isfile(gf):
                result = S.read_json(gf)
                st["gates"] = {}
                S.commit(rdir, st, "gates.done", phase=st["state"], iteration=st["iteration"],
                         data={"ok": result.get("ok"), "gate": result.get("gate")})
                return _after_gates(root, rdir, st, cfg, key, result)
            if _pid_alive(g.get("pid")):
                return next_action(root, run_id, cfg)
            # pid dead, no file -> respawn
            pd = os.path.join(rdir, key)
            _spawn_gates(root, rdir, st, pd)
            S.commit(rdir, st, "gates.start", phase=st["state"], iteration=st["iteration"], data={"respawn": True})
            return next_action(root, run_id, cfg)
        # 2. pending agent output?
        if not st.get("pending"):
            return next_action(root, run_id, cfg)
        p = st["pending"][0]
        of = os.path.join(root, p["out_file"])
        if not os.path.isfile(of):
            return next_action(root, run_id, cfg)
        # already consumed? (re-entrancy)
        for ev in S.read_events(rdir):
            if ev.get("event") == "consume" and ev.get("data", {}).get("phase_dir") == p["phase_dir"]:
                st["pending"] = []
                S.save_state(rdir, st)
                return next_action(root, run_id, cfg)
        try:
            out = S.read_json(of)
        except ValueError as e:
            out = None
            errs = ["out.json is not valid JSON: %s" % e]
        else:
            errs = schemas.check(p["phase"], out, st) if out is not None else ["out.json empty"]
        pd = os.path.join(root, p["phase_dir"])
        st["pending"] = []
        if errs:
            return _validation_fail(root, rdir, st, cfg, p, errs)
        S.commit(rdir, st, "consume", phase=p["phase"], iteration=st["iteration"], data={"phase_dir": p["phase_dir"]})
        st["validation_retry"] = 0
        st["retry"] = 0
        phase = p["phase"]
        if phase == "ARCHITECT":
            return _after_architect(root, rdir, st, cfg, out, pd)
        if phase in ("IMPLEMENT", "TEST"):
            key = "impl_phase_dirs" if phase == "IMPLEMENT" else "test_phase_dirs"
            st.setdefault(key, []).append(p["phase_dir"])
            _spawn_gates(root, rdir, st, pd)
            S.commit(rdir, st, "gates.start", phase=phase, iteration=st["iteration"], data={"phase_dir": p["phase_dir"]})
            return next_action(root, run_id, cfg)
        if phase == "REVIEW":
            st.setdefault("review_phase_dirs", []).append(p["phase_dir"])
            return _after_review(root, rdir, st, cfg, out, pd)
    return next_action(root, run_id, cfg)


def _validation_fail(root, rdir, st, cfg, p, errs):
    st["validation_retry"] = st.get("validation_retry", 0) + 1
    if st["validation_retry"] > cfg["validation_retries"]:
        return _block(root, rdir, st, "validation", "out.json for %s failed validation %d times: %s"
                      % (p["phase"], st["validation_retry"], "; ".join(errs)))
    st["retry"] = st.get("retry", 0) + 1
    S.commit(rdir, st, "validate", phase=p["phase"], iteration=st["iteration"],
             data={"ok": False, "errors": errs, "retry": st["validation_retry"]})
    # already inside the run lock — render the retry prompt directly
    pd = os.path.join(rdir, phase_dir_name(p["phase"], st["iteration"], st["retry"]))
    os.makedirs(os.path.join(pd, "logs"), exist_ok=True)
    pf = _render_prompt(root, st, cfg, p["phase"], pd)
    note = "\n\n## Retry — previous out.json rejected\n" + "\n".join("- " + e for e in errs) + "\n"
    with open(pf, "a") as f:
        f.write(note)
    st["pending"] = [{"phase": p["phase"], "iteration": st["iteration"], "workstream": None,
                      "out_file": os.path.relpath(os.path.join(pd, "out.json"), root),
                      "phase_dir": os.path.relpath(pd, root), "dispatched_at": S.now()}]
    S.commit(rdir, st, "dispatch", phase=p["phase"], iteration=st["iteration"],
             data={"agent": AGENT_FOR[p["phase"]], "retry_reason": errs, "phase_dir": os.path.relpath(pd, root)})
    return {"action": "dispatch", "phase": p["phase"], "iteration": st["iteration"], "agent": AGENT_FOR[p["phase"]],
            "model": cfg["models"][AGENT_FOR[p["phase"]]], "prompt_file": os.path.relpath(pf, root),
            "out_file": st["pending"][0]["out_file"], "workstream": None, "cwd": None,
            "retry_reason": "; ".join(errs)}


def _after_architect(root, rdir, st, cfg, out, pd):
    st["size"] = out["size"]
    st["workstreams"] = [{"name": w["name"], "owned": w["owned"], "depends_on": w.get("depends_on") or [],
                          "ac": w["ac"]} for w in out["workstreams"]]
    st["untestable"] = out.get("untestable") or []
    st["test_owned"] = out.get("test_owned") or {}
    st["ac"] = out["ac"]
    design_src = os.path.join(pd, out["design"])
    if os.path.isfile(design_src):
        with open(design_src) as f:
            S.atomic_write(os.path.join(rdir, "design.md"), f.read())
    if len(st["workstreams"]) > 1:
        # P0: no parallel. Collapse to sequential single workstream owning the union.
        owned = [p for w in st["workstreams"] for p in w["owned"]]
        ac = [a for w in st["workstreams"] for a in w["ac"]]
        st["workstreams"] = [{"name": "all", "owned": owned, "depends_on": [], "ac": ac}]
    st["state"] = "IMPLEMENT"
    S.commit(rdir, st, "transition", phase="IMPLEMENT", iteration=st["iteration"], data={"from": "ARCHITECT"})
    return next_action(root, st["run_id"], cfg)


def _after_gates(root, rdir, st, cfg, key, result):
    phase = st["state"]
    if phase == "IMPLEMENT":
        if result.get("ok"):
            st["gate_retry"] = 0
            st["state"] = "TEST"
            S.commit(rdir, st, "transition", phase="TEST", iteration=st["iteration"], data={"from": "IMPLEMENT"})
            return next_action(root, st["run_id"], cfg)
        return _gate_fail(root, rdir, st, cfg, phase, result)
    if phase == "TEST":
        cov = result.get("coverage") or {}
        if cov.get("status") == "unparseable":
            return _gate_fail(root, rdir, st, cfg, phase, result)
        if result.get("tests") == "fail":
            # tolerated only when the tester reported findings explaining it
            pdn = st["test_phase_dirs"][-1]
            to = S.read_json(os.path.join(root, pdn, "out.json")) or {}
            if not to.get("findings"):
                return _gate_fail(root, rdir, st, cfg, phase, result)
        st["gate_retry"] = 0
        st["verified_coverage"] = cov.get("total")
        st["last_test_gate"] = result
        st["state"] = "REVIEW"
        S.commit(rdir, st, "transition", phase="REVIEW", iteration=st["iteration"], data={"from": "TEST"})
        return next_action(root, st["run_id"], cfg)
    return next_action(root, st["run_id"], cfg)


def _gate_fail(root, rdir, st, cfg, phase, result):
    st["gate_retry"] = st.get("gate_retry", 0) + 1
    tail = ""
    for c in result.get("cmds", []):
        if c.get("exit") != 0:
            tail = "`%s` exit %s\n```\n%s\n```" % (c["cmd"], c["exit"], (c.get("tail") or "")[-800:])
            break
    if result.get("coverage", {}).get("status") == "unparseable":
        tail = tail or "coverage report `%s` could not be parsed" % result["coverage"].get("report")
    S.append_event(rdir, "gate.%s" % result.get("gate"), phase=phase, iteration=st["iteration"],
                   data={"ok": False, "retry": st["gate_retry"]})
    if st["gate_retry"] > cfg["gate_retries"]:
        return _block(root, rdir, st, "gate", "%s gate failed %d times.\n\n%s" % (phase, st["gate_retry"], tail))
    fb = "# Feedback for %s (gate retry %d)\n\n## Gate failure\n%s\n" % (phase, st["gate_retry"], tail)
    S.atomic_write(os.path.join(rdir, "feedback.md"), fb)
    st["retry"] = st.get("retry", 0) + 1
    S.save_state(rdir, st)
    return next_action(root, st["run_id"], cfg)


# --- verdict (spec §6.4 truth table) -----------------------------------------

def _same_ref(a, b):
    if not a or not b:
        return False
    a, b = str(a), str(b)
    return (a.startswith(b) or b.startswith(a)) and min(len(a), len(b)) >= 7


def verdict(out, test_gate, threshold, impl_files, new_tests, proof_ref):
    """Return (blockers, majors, route). Synthetic blockers carry source='gate'.

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
        blockers.append({"id": "G-TESTS", "severity": "blocker", "tag": "REQ", "file": None, "desc": "full test suite fails",
                         "route": "implementer", "verify": "manual", "source": "gate"})
    cov = tg.get("coverage") or {}
    if threshold is not None:
        if cov.get("status") == "ok":
            low = {f: v for f, v in (cov.get("per_file") or {}).items() if v is not None and v < threshold}
            if low:
                blockers.append({"id": "G-COV", "severity": "blocker", "tag": "TEST", "file": None,
                                 "desc": "per-file coverage below %s: %s" % (threshold, low),
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


def _after_review(root, rdir, st, cfg, out, pd):
    tg = st.get("last_test_gate") or {}
    impl_files = []
    for d in st.get("impl_phase_dirs", []):
        impl_files.extend((S.read_json(os.path.join(root, d, "out.json")) or {}).get("files", []))
    # only this iteration's test phase, minus tests already proven red in an earlier iteration
    last_test = st.get("test_phase_dirs", [])[-1:]
    cur_new = []
    for d in last_test:
        cur_new.extend((S.read_json(os.path.join(root, d, "out.json")) or {}).get("new_tests", []))
    proven = set(st.get("proven", []))
    need = [t for t in cur_new if t not in proven]
    proof_ref = st.get("proof_ref") or st.get("base_ref")
    blockers, majors, route = verdict(out, tg, st.get("coverage_threshold"), impl_files, need, proof_ref)
    # record this iteration's valid red rows so later iterations never re-prove them
    rg = tg.get("redgreen") or {}
    if _same_ref(rg.get("ref"), proof_ref):
        for r in rg.get("rows", []):
            if r.get("kind") in ("assertion", "compile") and r.get("test") not in proven:
                st.setdefault("proven", []).append(r["test"])
    S.atomic_write_json(os.path.join(pd, "verdict.json"),
                        {"verdict": "FAIL" if blockers else "PASS", "route": route, "blockers": blockers, "majors": majors})
    S.append_event(rdir, "review", phase="REVIEW", iteration=st["iteration"],
                   data={"verdict": "FAIL" if blockers else "PASS", "route": route, "blockers": len(blockers), "majors": len(majors)})
    if not blockers:
        st["state"] = "COMPLETE"
        S.commit(rdir, st, "complete", phase="REVIEW", iteration=st["iteration"], data={})
        gitutil.delete_refs(root, st["run_id"])
        return _done(root, rdir, st)
    # FAIL: feedback + route (P0: full round only, no inner loop)
    fb = ["# Feedback for iteration %d  (target: %s)\n" % (st["iteration"] + 1, route), "## Blockers",
          "| id | tag | file:line | desc | verify |", "|---|---|---|---|---|"]
    for b in blockers:
        fb.append("| %s | %s | %s:%s | %s | `%s` |" % (b["id"], b["tag"], b.get("file"), b.get("line"), b["desc"], b.get("verify")))
    fb.append("\n## Majors (fix if cheap)")
    for m in majors:
        fb.append("- %s [%s] %s" % (m["id"], m["tag"], m["desc"]))
    S.atomic_write(os.path.join(rdir, "feedback.md"), "\n".join(fb) + "\n")
    st["iteration"] += 1
    if st["iteration"] > st["cap"]:
        return _block(root, rdir, st, "convergence", "iteration cap %d exceeded; last route %s" % (st["cap"], route))
    st["iter_ref"] = gitutil.snapshot(root, "%s/iter-%d" % (st["run_id"], st["iteration"]))
    # proof ref = snapshot taken before the last CODE change. A tester-only round changes no code,
    # so its new tests are still proven against the previous ref (where the behaviour did not exist).
    if route in ("implementer", "architecter"):
        st["proof_ref"] = st["iter_ref"]
    st["state"] = {"implementer": "IMPLEMENT", "tester": "TEST", "architecter": "ARCHITECT"}[route]
    st["retry"] = 0
    S.commit(rdir, st, "transition", phase=st["state"], iteration=st["iteration"], data={"from": "REVIEW", "route": route})
    return next_action(root, st["run_id"], cfg)


def _block(root, rdir, st, cause, reason):
    st["state"] = "BLOCKED"
    st["block_cause"] = cause
    st["pending"] = []
    st["gates"] = {}
    events = S.read_events(rdir)
    lines = ["# BLOCKED — run %s" % st["run_id"], "", "Cause: **%s**" % cause, "", reason, "", "## Task", st["task"], "",
             "## Timeline", "| ts | event | phase | iteration | data |", "|---|---|---|---|---|"]
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
