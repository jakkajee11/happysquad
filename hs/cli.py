"""hs command line (spec §4). Every command prints one JSON line on stdout."""
import argparse
import json
import os
import subprocess
import sys
import time

from . import config as C, gates, machine, schemas, state as S


def _root(args):
    return os.path.abspath(args.root or os.getcwd())


def _rid(root, args):
    rid = getattr(args, "run", None) or S.current_run_id(root)
    if not rid:
        _out({"action": "error", "message": "no current run"})
        sys.exit(2)
    return rid


def _out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _exit_for(act):
    return 0 if act.get("action") != "error" else 2


def _resolve(root, rid, cfg, act):
    """Turn a bare dispatch(_many) (prompts not rendered yet) into rendered ones; drive internal states.

    Safe to call repeatedly. Loops because an `advance` reason can chain (gates done → internal → dispatch).
    """
    for _ in range(8):
        a = act.get("action")
        if a in ("dispatch", "dispatch_many") and act.get("_specs"):
            act = machine.dispatch(root, rid, cfg)
            continue
        if a == "advance":
            act = machine.advance(root, rid, cfg)
            if act.get("action") == "advance":
                # advance() returned next_action() with nothing consumable → genuinely idle; avoid spinning
                act = machine.next_action(root, rid, cfg)
                if act.get("action") == "advance":
                    break
            continue
        break
    act.pop("_specs", None)
    return act


def _awaiting(act):
    """Files a driver must wait on for this action, or [] when the action is actionable now."""
    if act.get("action") == "wait":
        return act["files"]
    return []


def cmd_init(args):
    root = _root(args)
    d = S.hs_dir(root)
    os.makedirs(os.path.join(d, "runs"), exist_ok=True)
    gi = os.path.join(d, ".gitignore")
    if not os.path.isfile(gi):
        # `*` with re-includes: the directory itself stays visible to git (so config.json can be
        # committed) while runs/, current, .lock etc. are ignored. A bare `*` would hide the dir
        # and git status would list `.happysquad/` as untracked forever.
        S.atomic_write(gi, "/*\n!/.gitignore\n!/config.json\n!/stack-profile.md\n!/stack-profile.json\n!/risk-patterns.json\n")
    cp = C.config_path(root)
    seeded = {}
    if not os.path.isfile(cp):
        seeded = seed_commands(root)
        S.atomic_write_json(cp, {"build_cmd": seeded.get("build_cmd"), "test_cmd": seeded.get("test_cmd"),
                                 "coverage_report": seeded.get("coverage_report")})
    cfg_now = C.load(root, warn=False)
    note = None if cfg_now.get("test_cmd") else "no test command detected — set test_cmd in .happysquad/config.json before `hs run start`"
    _out({"ok": True, "config": os.path.relpath(cp, root), "seeded": seeded, "note": note})


def seed_commands(root):
    """Best-effort build/test/coverage commands from manifests (spec §7.0: hs init seeds them).

    Order: package.json scripts → pyproject/pytest → go.mod → Cargo.toml → *.csproj. Returns {} when unsure.
    """
    import glob
    import json as _json
    pj = os.path.join(root, "package.json")
    if os.path.isfile(pj):
        try:
            scripts = _json.load(open(pj)).get("scripts") or {}
        except ValueError:
            scripts = {}
        pm = "pnpm" if os.path.isfile(os.path.join(root, "pnpm-lock.yaml")) else "yarn" if os.path.isfile(os.path.join(root, "yarn.lock")) else "npm"
        run = ("%s run " % pm) if pm != "yarn" else "yarn "
        out = {}
        if "build" in scripts:
            out["build_cmd"] = "%sbuild" % run
        elif "lint" in scripts:
            out["build_cmd"] = "%slint" % run
        if "test" in scripts:
            out["test_cmd"] = "%s test" % pm if pm != "yarn" else "yarn test"
            t = scripts["test"]
            if "vitest" in t or "jest" in t:
                out["coverage_report"] = "coverage/coverage-summary.json"
            elif "lcov" in t or "c8" in t or "nyc" in t:
                out["coverage_report"] = "coverage/lcov.info"
        return out
    if os.path.isfile(os.path.join(root, "pyproject.toml")) or glob.glob(os.path.join(root, "pytest.ini")) or glob.glob(os.path.join(root, "tests", "test_*.py")):
        return {"build_cmd": "python3 -m compileall -q .", "test_cmd": "python3 -m pytest -q --cov=. --cov-report=json",
                "coverage_report": "coverage.json"}
    if os.path.isfile(os.path.join(root, "go.mod")):
        return {"build_cmd": "go build ./...", "test_cmd": "go test ./... -coverprofile=coverage.out", "coverage_report": None}
    if os.path.isfile(os.path.join(root, "Cargo.toml")):
        return {"build_cmd": "cargo build", "test_cmd": "cargo test", "coverage_report": None}
    if glob.glob(os.path.join(root, "*.csproj")) or glob.glob(os.path.join(root, "*.sln")):
        return {"build_cmd": "dotnet build", "test_cmd": "dotnet test --collect:\"XPlat Code Coverage\"", "coverage_report": None}
    return {}


def cmd_config(args):
    _out(C.load(_root(args)))


def cmd_run(args):
    root = _root(args)
    cfg = C.load(root)
    if args.no_parallel:
        cfg["no_parallel"] = True
    if args.sub == "start":
        driver = args.driver or cfg.get("driver", "agent-tool")
        if driver in ("headless", "fake"):
            from . import drivers
            if driver == "fake" and not os.environ.get("HS_CLAUDE"):
                os.environ["HS_CLAUDE"] = os.path.join(machine.PLUGIN_ROOT, "evals", "fake_claude.py")
            iso = "none" if args.no_isolate else None
            act = drivers.run_headless(root, args.task, cfg, lite=args.lite, isolate_wt=iso)
            _out(act)
            sys.exit(_exit_for(act))
        act = machine.start(root, args.task, cfg, lite=args.lite, driver=driver)
        if act.get("action") != "error":
            act = _resolve(root, S.current_run_id(root), cfg, act)
        _out(act)
        sys.exit(_exit_for(act))
    _out({"action": "error", "message": "unknown run subcommand"})
    sys.exit(2)


def cmd_next(args):
    root = _root(args)
    cfg = C.load(root)
    rid = _rid(root, args)
    act = _resolve(root, rid, cfg, machine.next_action(root, rid, cfg))
    _out(act)
    sys.exit(_exit_for(act))


def cmd_advance(args):
    root = _root(args)
    cfg = C.load(root)
    rid = _rid(root, args)
    act = _resolve(root, rid, cfg, machine.advance(root, rid, cfg))
    _out(act)
    sys.exit(_exit_for(act))


def cmd_wait(args):
    """Poll in-process until the awaited files exist, then advance. Prints `wait` again on timeout."""
    root = _root(args)
    cfg = C.load(root)
    rid = _rid(root, args)
    rdir = S.run_dir(root, rid)
    deadline = time.time() + args.timeout
    while True:
        act = _resolve(root, rid, cfg, machine.next_action(root, rid, cfg))
        files = _awaiting(act)
        if not files:
            _out(act)
            sys.exit(_exit_for(act))
        paths = [os.path.join(root, f) for f in files]
        # agents: any single output is enough to make progress (waves consume per workstream);
        # gates: same — advance() handles each finished child independently
        if any(os.path.isfile(p) and os.path.getsize(p) > 0 for p in paths):
            act = _resolve(root, rid, cfg, machine.advance(root, rid, cfg))
            if _awaiting(act):
                if act.get("files") == files:
                    time.sleep(args.interval)
                continue
            _out(act)
            sys.exit(_exit_for(act))
        S.atomic_write(os.path.join(rdir, ".orchestrator"), S.now() + "\n")
        if time.time() >= deadline:
            _out({"action": "wait", "for": act.get("for", "agents"), "files": files, "timed_out": True})
            sys.exit(0)
        time.sleep(args.interval)


def cmd_gates_internal(args):
    root = _root(args)
    cfg = C.load(root)
    pd = os.path.join(root, args.phase_dir)
    rid = os.path.basename(os.path.dirname(pd.rstrip("/")))
    rdir = S.run_dir(root, rid)
    res = gates.run_gates(root, rdir, pd, cfg)
    _out({"ok": res.get("ok"), "gate": res.get("gate")})


def cmd_redgreen(args):
    from . import redgreen
    root = _root(args)
    cfg = C.load(root)
    tpl = args.cmd or cfg.get("redgreen_cmd") or ((cfg.get("test_cmd") or "") + " {file}")
    # the coverage report's directory is usually gitignored and therefore absent in a fresh worktree
    mkdirs = [os.path.dirname(cfg["coverage_report"])] if cfg.get("coverage_report") else []
    res = redgreen.prove(root, args.ref, args.tests, tpl, copy=args.copy or (), link=args.link or (),
                         timeout=cfg["gate_timeout"], mkdirs=mkdirs)
    out = args.out
    if not out:
        rid = S.current_run_id(root)
        st = S.load_state(S.run_dir(root, rid)) if rid else None
        if st and st.get("pending"):
            out = os.path.join(root, st["pending"][0]["phase_dir"], "redgreen.json")
    if out:
        S.atomic_write_json(out, res)
        res["written"] = os.path.relpath(out, root)
    _out(res)


def cmd_fleet(args):
    from . import fleet as F
    root = _root(args)
    cfg = C.load(root)
    if args.sub == "start":
        tasks = []
        if args.tasks_file:
            for line in open(os.path.join(root, args.tasks_file)):
                line = line.strip().lstrip("-*").strip()
                if line and not line.startswith("#"):
                    tasks.append(line)
        tasks += args.task or []
        act = F.start(root, tasks, cfg, max_parallel=args.max, lite=args.lite)
        _out(act)
        sys.exit(_exit_for(act))
    fid = args.fleet or F.current_fleet(root)
    if not fid:
        _out({"action": "error", "message": "no current fleet"})
        sys.exit(2)
    if args.sub == "advance":
        _out(F.advance(root, fid, cfg))
    elif args.sub == "wait":
        _out(F.wait(root, fid, cfg, timeout=args.timeout, interval=args.interval))
    elif args.sub == "status":
        _out(F.summary(root, fid))
    elif args.sub == "cleanup":
        _out(F.cleanup(root, fid, cfg, keep_failed=not args.all))


def cmd_validate(args):
    root = _root(args)
    out = S.read_json(os.path.join(root, args.out_file))
    if out is None:
        _out({"ok": False, "errors": ["file missing or empty"]})
        sys.exit(1)
    phase = args.phase or out.get("phase")
    st = None
    rid = S.current_run_id(root)
    if rid:
        st = S.load_state(S.run_dir(root, rid))
    errs = schemas.check(phase, out, st)
    _out({"ok": not errs, "phase": phase, "errors": errs})
    sys.exit(0 if not errs else 1)


def cmd_risk(args):
    from . import risk
    root = _root(args)
    rid = getattr(args, "run", None) or S.current_run_id(root)
    base = args.base
    if not base and rid:
        st = S.load_state(S.run_dir(root, rid)) or {}
        base = st.get("base_ref")
    _out(risk.detect(root, base))


def cmd_status(args):
    root = _root(args)
    rid = getattr(args, "run", None) or S.current_run_id(root)
    if not rid:
        _out({"runs": 0})
        return
    st = S.load_state(S.run_dir(root, rid))
    if not st:
        _out({"run_id": rid, "state": "missing"})
        return
    _out({"run_id": rid, "state": st["state"], "iteration": st["iteration"], "cap": st["cap"],
          "mode": st.get("mode"), "lite": st.get("lite"), "inner_pass": st.get("inner_pass"),
          "workstreams": [{"name": w["name"], "impl": w.get("impl"), "test": w.get("test")} for w in st.get("workstreams", [])],
          "pending": [{"phase": p["phase"], "ws": p.get("ws"), "axis": p.get("axis")} for p in st.get("pending", [])],
          "gates": list(st.get("gates", {}).keys()),
          "task": st["task"][:80], "updated_at": st.get("updated_at"), "block_cause": st.get("block_cause")})


def cmd_resume(args):
    root = _root(args)
    cfg = C.load(root)
    rid = _rid(root, args)
    act = _resolve(root, rid, cfg, machine.resume(root, rid, cfg))
    _out(act)
    sys.exit(_exit_for(act))


def cmd_block(args):
    root = _root(args)
    cfg = C.load(root)
    rid = _rid(root, args)
    _out(machine.block_manual(root, rid, cfg, args.cause, args.reason))


_SOURCE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css", ".prisma", ".py", ".go",
                ".rs", ".java", ".rb", ".php", ".c", ".cpp", ".h", ".swift", ".kt")


def _git(root, *args):
    """Run a git command in `root`; None on any failure (not a repo, no git, bad ref)."""
    try:
        return subprocess.check_output(["git"] + list(args), cwd=root, text=True,
                                        stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def _session_path(root):
    return os.path.join(S.hs_dir(root), ".session")


def _hook_session_start(root):
    lines = []
    rid = S.current_run_id(root)
    st = S.load_state(S.run_dir(root, rid)) if rid else None
    if st:
        state = st.get("state")
        if state == "BLOCKED":
            lines.append("[happysquad] run %s is BLOCKED (cause %s) — read .happysquad/runs/%s/BLOCKED.md"
                         % (rid, st.get("block_cause", "?"), rid))
        elif state != "COMPLETE":
            lines.append("[happysquad] in-progress run %s at %s (iteration %d/%d). Run /squad-resume to continue."
                         % (rid, state, st.get("iteration", 0), st.get("cap", 0)))
            ua = st.get("updated_at")
            head_ts = _git(root, "log", "-1", "--format=%cI")
            if ua and head_ts:
                try:
                    drifted = S.parse_ts(head_ts) > S.parse_ts(ua)
                except Exception:
                    drifted = False
                if drifted:
                    task = str(st.get("task", "?")).splitlines()[0][:60]
                    lines.append('  ⚠ DRIFT: run is at %s (iter %s) for "%s",' % (state, st.get("iteration", "?"), task))
                    lines.append('    but a commit landed after it last updated — likely direct work bypassed the loop.')
                    lines.append('    Reconcile: /squad-status, then /squad-resume or mark the run done.')
    if lines:
        print("\n".join(lines))
    S.atomic_write_json(_session_path(root), {"head": _git(root, "rev-parse", "HEAD"), "started_at": S.now(), "nudged": False})


def _hook_stop(root, cfg):
    if not cfg.get("hooks", {}).get("stop_progress_nudge"):
        return
    sp = _session_path(root)
    sess = S.read_json(sp) or {}
    if sess.get("nudged"):
        return
    changed = set()
    head = _git(root, "rev-parse", "HEAD")
    start = sess.get("head")
    if start and head and start != head:
        diff = _git(root, "diff", "--name-only", start, head)
        changed.update(l for l in (diff or "").splitlines() if l.strip())
    status = _git(root, "status", "--porcelain")
    for line in (status or "").splitlines():
        path = line[3:].strip()
        if path:
            changed.add(path)
    if not changed or not any(p.endswith(_SOURCE_EXTS) for p in changed):
        return
    if any(os.path.basename(p).lower() == "progress.md" for p in changed):
        return
    sess["nudged"] = True
    S.atomic_write_json(sp, sess)
    sys.stderr.write("Sync reminder: source changed this session but no progress log was updated. Add a "
                      "one-line entry to PROGRESS.md (or .happysquad/progress.md) — what changed / what's "
                      "next — so the next session can resume, then finish.\n")
    sys.exit(2)


def cmd_hook(args):
    try:
        if os.environ.get("HS_CHILD") == "1":
            return
        root = _root(args)
        if not os.path.isdir(S.hs_dir(root)):
            return
        if args.which == "session-start":
            _hook_session_start(root)
        elif args.which == "stop":
            _hook_stop(root, C.load(root, warn=False))
    except Exception:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hs")
    ap.add_argument("--root", help="repo root (default: cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(fn=cmd_init)
    sub.add_parser("config").set_defaults(fn=cmd_config)

    r = sub.add_parser("run")
    rs = r.add_subparsers(dest="sub", required=True)
    rst = rs.add_parser("start")
    rst.add_argument("task")
    rst.add_argument("--lite", action="store_true")
    rst.add_argument("--no-parallel", action="store_true")
    rst.add_argument("--no-isolate", action="store_true", help="headless: run in the working tree instead of a worktree")
    rst.add_argument("--driver", choices=["agent-tool", "headless", "fake"])
    r.set_defaults(fn=cmd_run)

    an = sub.add_parser("answer")
    an.add_argument("key")
    an.add_argument("value")
    an.add_argument("--run")
    an.set_defaults(fn=lambda a: _out(machine.answer(_root(a), _rid(_root(a), a), C.load(_root(a)), a.key, a.value)))

    rk = sub.add_parser("risk")
    rk.add_argument("--run")
    rk.add_argument("--base")
    rk.set_defaults(fn=cmd_risk)

    for name, fn in (("next", cmd_next), ("advance", cmd_advance), ("resume", cmd_resume)):
        p = sub.add_parser(name)
        p.add_argument("--run")
        p.set_defaults(fn=fn)

    w = sub.add_parser("wait")
    w.add_argument("--run")
    w.add_argument("--timeout", type=int, default=540)
    w.add_argument("--interval", type=float, default=5.0)
    w.set_defaults(fn=cmd_wait)

    g = sub.add_parser("_gates")
    g.add_argument("phase_dir")
    g.set_defaults(fn=cmd_gates_internal)

    rg = sub.add_parser("redgreen")
    rg.add_argument("--ref", required=True)
    rg.add_argument("--tests", nargs="+", required=True)
    rg.add_argument("--cmd", help="template with {file}; default config.redgreen_cmd or '<test_cmd> {file}'")
    rg.add_argument("--copy", nargs="*")
    rg.add_argument("--link", nargs="*")
    rg.add_argument("--out")
    rg.set_defaults(fn=cmd_redgreen)

    fl = sub.add_parser("fleet")
    fls = fl.add_subparsers(dest="sub", required=True)
    fs = fls.add_parser("start")
    fs.add_argument("task", nargs="*", help="task descriptions (or use --tasks-file)")
    fs.add_argument("--tasks-file")
    fs.add_argument("--max", type=int)
    fs.add_argument("--lite", action="store_true")
    for name in ("advance", "status"):
        p = fls.add_parser(name)
        p.add_argument("--fleet")
    fw = fls.add_parser("wait")
    fw.add_argument("--fleet")
    fw.add_argument("--timeout", type=int, default=540)
    fw.add_argument("--interval", type=float, default=5.0)
    fc = fls.add_parser("cleanup")
    fc.add_argument("--fleet")
    fc.add_argument("--all", action="store_true", help="remove BLOCKED/stalled worktrees too")
    fl.set_defaults(fn=cmd_fleet)

    v = sub.add_parser("validate")
    v.add_argument("out_file")
    v.add_argument("--phase")
    v.set_defaults(fn=cmd_validate)

    s = sub.add_parser("status")
    s.add_argument("--run")
    s.set_defaults(fn=cmd_status)

    b = sub.add_parser("block")
    b.add_argument("reason")
    b.add_argument("--run")
    b.add_argument("--cause", default="agent")
    b.set_defaults(fn=cmd_block)

    h = sub.add_parser("hook")
    h.add_argument("which", choices=["session-start", "stop"])
    h.set_defaults(fn=cmd_hook)

    args = ap.parse_args(argv)
    args.fn(args)
