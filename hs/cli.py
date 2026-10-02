"""hs command line (spec §4). Every command prints one JSON line on stdout."""
import argparse
import json
import os
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
    """Turn a bare `dispatch` (no prompt rendered yet) into a rendered one. Safe to call repeatedly."""
    if act.get("action") == "dispatch" and not act.get("prompt_file"):
        act = machine.dispatch(root, rid, cfg)
    act.pop("_phase_dir", None)
    return act


def _awaiting(act):
    """Files a driver must wait on for this action, or [] when the action is actionable now."""
    if act.get("action") == "wait":
        return act["files"]
    if act.get("action") == "dispatch" and act.get("redispatch"):
        return [act["out_file"]]
    return []


def cmd_init(args):
    root = _root(args)
    d = S.hs_dir(root)
    os.makedirs(os.path.join(d, "runs"), exist_ok=True)
    gi = os.path.join(d, ".gitignore")
    if not os.path.isfile(gi):
        S.atomic_write(gi, "*\n!.gitignore\n!config.json\n!stack-profile.md\n!stack-profile.json\n!risk-patterns.json\n")
    cp = C.config_path(root)
    if not os.path.isfile(cp):
        S.atomic_write_json(cp, {"build_cmd": None, "test_cmd": None, "coverage_report": None})
    _out({"ok": True, "config": os.path.relpath(cp, root)})


def cmd_config(args):
    _out(C.load(_root(args)))


def cmd_run(args):
    root = _root(args)
    cfg = C.load(root)
    if args.sub == "start":
        act = machine.start(root, args.task, cfg, lite=args.lite, driver=args.driver)
        if act.get("action") == "dispatch":
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
            if act.get("action") == "advance":
                act = _resolve(root, rid, cfg, machine.advance(root, rid, cfg))
                if _awaiting(act):
                    continue
            _out(act)
            sys.exit(_exit_for(act))
        paths = [os.path.join(root, f) for f in files]
        if all(os.path.isfile(p) and os.path.getsize(p) > 0 for p in paths):
            act = _resolve(root, rid, cfg, machine.advance(root, rid, cfg))
            if _awaiting(act):
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
          "pending": [p["phase"] for p in st.get("pending", [])], "gates": list(st.get("gates", {}).keys()),
          "task": st["task"][:80], "updated_at": st.get("updated_at"), "block_cause": st.get("block_cause")})


def cmd_resume(args):
    root = _root(args)
    cfg = C.load(root)
    rid = _rid(root, args)
    from . import gitutil
    gitutil.prune(root)
    rdir = S.run_dir(root, rid)
    S.append_event(rdir, "resume", data={})
    act = _resolve(root, rid, cfg, machine.advance(root, rid, cfg))
    _out(act)
    sys.exit(_exit_for(act))


def cmd_block(args):
    root = _root(args)
    cfg = C.load(root)
    rid = _rid(root, args)
    _out(machine.block_manual(root, rid, cfg, args.cause, args.reason))


def cmd_hook(args):
    if os.environ.get("HS_CHILD") == "1":
        return
    root = _root(args)
    if not os.path.isdir(S.hs_dir(root)):
        return
    if args.which == "session-start":
        rid = S.current_run_id(root)
        if rid:
            st = S.load_state(S.run_dir(root, rid))
            if st and st["state"] not in ("COMPLETE", "BLOCKED"):
                print("[happysquad] in-progress run %s at %s (iteration %d). Run /squad-resume to continue."
                      % (rid, st["state"], st["iteration"]))


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
    rst.add_argument("--driver")
    r.set_defaults(fn=cmd_run)

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
