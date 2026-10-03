"""Fleet (spec §12): N independent headless runs, one worktree each, scheduled up to max_parallel.

State: .happysquad/fleets/<fleet-id>/fleet.json (+ tasks.md, aggregate-report.md). Each child is a
normal headless run started with `hs run start --driver headless` inside its own worktree; the child
owns its run state under <worktree>/.happysquad/runs/<run-id>/.

`start` creates the fleet; `advance` reconciles children and launches pending ones; `wait` loops
advance until the fleet is terminal. All three are safe to call repeatedly.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

from . import config as C, gitutil, machine, state as S

HS_BIN = machine.HS_BIN
TERMINAL_CHILD = ("COMPLETE", "BLOCKED", "stalled", "failed")
QUIET_SECS = 1800


def fleets_dir(root):
    return os.path.join(S.hs_dir(root), "fleets")


def fleet_dir(root, fid):
    return os.path.join(fleets_dir(root), fid)


def load(root, fid):
    return S.read_json(os.path.join(fleet_dir(root, fid), "fleet.json"))


def save(root, fid, f):
    f["updated_at"] = S.now()
    S.atomic_write_json(os.path.join(fleet_dir(root, fid), "fleet.json"), f)


def current_fleet(root):
    p = os.path.join(S.hs_dir(root), "current-fleet")
    if os.path.isfile(p):
        return open(p).read().strip() or None
    return None


def _slug(text, n=5):
    words = re.findall(r"[A-Za-z0-9]+", text)[:n]
    return "-".join(w.lower() for w in words)[:40] or "task"


def _child_wt(root, fid, slug):
    from .drivers import worktree_base
    return os.path.join(worktree_base(root), "fleet-%s" % fid, slug)


# --- start -----------------------------------------------------------------------

def start(root, tasks, cfg, max_parallel=None, lite=False, frontier=False, drain=False):
    if not gitutil.is_repo(root):
        return {"action": "error", "message": "not a git repository"}
    if not cfg.get("test_cmd"):
        return {"action": "error", "message": "config.test_cmd is null — set it in .happysquad/config.json"}
    drain = bool(drain)
    frontier = bool(frontier) or drain
    if frontier:
        from . import frontier as FR
        fr = FR.read(root)
        if not fr["frontier"]:
            return {"action": "fleet", "status": "empty", "note": fr.get("note") or "Frontier empty — nothing to drain."}
        items = [((t.get("task") or t.get("title") or t["ref"]).strip(), t["ref"]) for t in fr["frontier"]]
    else:
        items = [(t.strip(), None) for t in tasks if t and t.strip()]
    if not items:
        return {"action": "error", "message": "no tasks"}
    ts = S.now().replace("-", "").replace(":", "").replace("T", "-").replace("Z", "")
    fid = "%s-%s" % (ts, _slug(items[0][0]))
    fd = fleet_dir(root, fid)
    os.makedirs(fd, exist_ok=True)
    S.atomic_write(os.path.join(fd, "tasks.md"), "\n".join("- %s" % t for t, _ in items) + "\n")
    seen = set()
    children = []
    for t, ticket in items:
        slug = _slug(t)
        base = slug
        k = 2
        while slug in seen:
            slug = "%s-%d" % (base, k); k += 1
        seen.add(slug)
        children.append({"slug": slug, "task": t, "ticket": ticket, "passed": False, "status": "pending",
                         "worktree": None, "branch": None, "run_id": None, "pid": None, "started_at": None,
                         "finished_at": None, "verdict": None, "iterations": None, "cause": None, "redispatched": False})
    mp = max_parallel or (1 if drain else cfg.get("max_parallel", 4))
    f = {"fleet_id": fid, "status": "in_progress", "max_parallel": mp,
         "lite": bool(lite), "drain": drain, "frontier": frontier, "base": gitutil.head(root),
         "started_at": S.now(), "children": children}
    save(root, fid, f)
    S.atomic_write(os.path.join(S.hs_dir(root), "current-fleet"), fid + "\n")
    return advance(root, fid, cfg)


# --- children ---------------------------------------------------------------------

def _launch(root, fid, f, c, cfg):
    """Create the child's worktree and start `hs run start --driver headless --no-isolate` inside it."""
    wt = _child_wt(root, fid, c["slug"])
    branch = "fleet/%s/%s" % (fid, c["slug"])
    os.makedirs(os.path.dirname(wt), exist_ok=True)
    if not os.path.isdir(wt):
        gitutil.git(root, "worktree", "add", "-q", "-b", branch, wt, f.get("base") or "HEAD")
    src = os.path.join(root, ".happysquad")
    dst = os.path.join(wt, ".happysquad")
    os.makedirs(dst, exist_ok=True)
    for name in ("config.json", "stack-profile.md", "stack-profile.json", "risk-patterns.json", ".gitignore"):
        p = os.path.join(src, name)
        if os.path.isfile(p):
            shutil.copy(p, os.path.join(dst, name))
    log = os.path.join(fleet_dir(root, fid), "child-%s.log" % c["slug"])
    argv = [sys.executable, HS_BIN, "run", "start", c["task"], "--driver", "headless", "--no-isolate"]
    if f.get("lite"):
        argv.append("--lite")
    env = dict(os.environ, HS_CHILD="1")
    with open(log, "a") as lf:
        p = subprocess.Popen(argv, cwd=wt, stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT,
                             env=env, start_new_session=True)
    c.update({"status": "in_progress", "worktree": wt, "branch": branch, "pid": p.pid, "started_at": S.now()})


def _pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _child_state(c):
    """(run_id, state dict) of the child's run, or (None, None) before it has started one."""
    if not c.get("worktree"):
        return None, None
    rid = S.current_run_id(c["worktree"])
    if not rid:
        return None, None
    return rid, S.load_state(S.run_dir(c["worktree"], rid))


def _newest_mtime(path):
    newest = 0.0
    for dp, _, fns in os.walk(path):
        for fn in fns:
            try:
                newest = max(newest, os.path.getmtime(os.path.join(dp, fn)))
            except OSError:
                pass
    return newest


def _reconcile(root, fid, f, c, cfg):
    """Update one in-progress child from its worktree. Returns True when its status changed."""
    rid, st = _child_state(c)
    if st:
        c["run_id"] = rid
        c["iterations"] = st.get("iteration")
        if st["state"] in ("COMPLETE", "BLOCKED"):
            c["status"] = st["state"]
            c["verdict"] = "PASS" if st["state"] == "COMPLETE" else "BLOCKED"
            c["cause"] = st.get("block_cause")
            c["finished_at"] = c["finished_at"] or S.now()
            c["pid"] = None
            return True
    if _pid_alive(c.get("pid")):
        return False
    # driver process is gone and the run is not terminal
    quiet_for = time.time() - max(_newest_mtime(os.path.join(c["worktree"], ".happysquad")) if c.get("worktree") else 0,
                                  S.parse_ts(c["started_at"]).timestamp() if c.get("started_at") else 0)
    if st is None and quiet_for < 120:
        return False  # just launched; give `run start` a moment to write state
    if not c.get("redispatched"):
        # one re-dispatch: `hs resume` continues the child's own run in place
        log = os.path.join(fleet_dir(root, fid), "child-%s.log" % c["slug"])
        argv = [sys.executable, HS_BIN, "resume"] if st else [sys.executable, HS_BIN, "run", "start", c["task"], "--driver", "headless", "--no-isolate"]
        with open(log, "a") as lf:
            lf.write("\n[fleet] driver exited without a terminal state; re-dispatching (%s)\n" % " ".join(argv[2:]))
            p = subprocess.Popen(argv, cwd=c["worktree"], stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT,
                                 env=dict(os.environ, HS_CHILD="1"), start_new_session=True)
        c["pid"] = p.pid
        c["redispatched"] = True
        return True
    c["status"] = "stalled"
    c["verdict"] = "STALLED"
    c["finished_at"] = S.now()
    c["pid"] = None
    return True


def _mark_passed_children(root, f):
    """Label COMPLETE children's tickets `squad:passed` once (spec §12, 1.1). Never closes an issue."""
    from . import frontier as FR
    changed = False
    for c in f["children"]:
        if c["status"] == "COMPLETE" and c.get("ticket") and not c.get("passed"):
            try:
                FR.mark_passed(root, c["ticket"])
            except Exception:
                pass
            c["passed"] = True
            changed = True
    return changed


def _pump_frontier(root, f):
    """Drain mode only: append any newly-ready, not-yet-a-child ticket as a pending child."""
    from . import frontier as FR
    fr = FR.read(root)
    existing_tickets = {c["ticket"] for c in f["children"] if c.get("ticket")}
    existing_slugs = {c["slug"] for c in f["children"]}
    added = False
    for t in fr["frontier"]:
        if t["ref"] in existing_tickets:
            continue
        task = (t.get("task") or t.get("title") or t["ref"]).strip()
        slug = _slug(task)
        base, k = slug, 2
        while slug in existing_slugs:
            slug = "%s-%d" % (base, k); k += 1
        existing_slugs.add(slug)
        f["children"].append({"slug": slug, "task": task, "ticket": t["ref"], "passed": False, "status": "pending",
                              "worktree": None, "branch": None, "run_id": None, "pid": None, "started_at": None,
                              "finished_at": None, "verdict": None, "iterations": None, "cause": None, "redispatched": False})
        existing_tickets.add(t["ref"])
        added = True
    return added


def advance(root, fid, cfg):
    f = load(root, fid)
    if f is None:
        return {"action": "error", "message": "no such fleet %s" % fid}
    if f["status"] != "in_progress":
        return summary(root, fid, f)
    changed = False
    for c in f["children"]:
        if c["status"] == "in_progress":
            changed |= _reconcile(root, fid, f, c, cfg)
    if _mark_passed_children(root, f):
        changed = True
    if f.get("frontier") and f.get("drain"):
        if _pump_frontier(root, f):
            changed = True
    running = [c for c in f["children"] if c["status"] == "in_progress"]
    pending = [c for c in f["children"] if c["status"] == "pending"]
    while pending and len(running) < f["max_parallel"]:
        c = pending.pop(0)
        try:
            _launch(root, fid, f, c, cfg)
        except Exception as e:  # worktree add failure etc. — do not take the fleet down
            c.update({"status": "failed", "verdict": "FAILED", "cause": "launch: %s" % str(e)[:200], "finished_at": S.now()})
        running.append(c)
        changed = True
    if all(c["status"] in TERMINAL_CHILD for c in f["children"]):
        f["status"] = "complete"
        f["finished_at"] = S.now()
        _report(root, fid, f)
        changed = True
    if changed:
        save(root, fid, f)
    return summary(root, fid, f)


def wait(root, fid, cfg, timeout=540, interval=5):
    deadline = time.time() + timeout
    while True:
        s = advance(root, fid, cfg)
        if s.get("status") != "in_progress":
            return s
        if time.time() >= deadline:
            s["timed_out"] = True
            return s
        time.sleep(interval)


def summary(root, fid, f=None):
    f = f or load(root, fid)
    counts = {}
    for c in f["children"]:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    out = {"action": "fleet", "fleet_id": fid, "status": f["status"], "max_parallel": f["max_parallel"], "counts": counts,
           "children": [{"slug": c["slug"], "status": c["status"], "verdict": c.get("verdict"), "iterations": c.get("iterations"),
                         "branch": c.get("branch"), "worktree": c.get("worktree"), "cause": c.get("cause"),
                         "ticket": c.get("ticket"), "passed": c.get("passed")} for c in f["children"]]}
    if f["status"] == "complete":
        out["report"] = os.path.relpath(os.path.join(fleet_dir(root, fid), "aggregate-report.md"), root)
        out["merge"] = ["git merge --no-ff %s" % c["branch"] for c in f["children"] if c["status"] == "COMPLETE"]
    return out


def _report(root, fid, f):
    lines = ["# Fleet %s — aggregate report" % fid, "",
             "Started: %s · Ended: %s · Total: %d · Passed: %d · Blocked: %d · Stalled/failed: %d" % (
                 f["started_at"], f.get("finished_at"), len(f["children"]),
                 sum(1 for c in f["children"] if c["status"] == "COMPLETE"),
                 sum(1 for c in f["children"] if c["status"] == "BLOCKED"),
                 sum(1 for c in f["children"] if c["status"] in ("stalled", "failed"))),
             "", "| slug | verdict | iterations | branch | notes |", "|---|---|---|---|---|"]
    for c in f["children"]:
        note = c.get("cause") or ("ready to merge" if c["status"] == "COMPLETE" else "")
        lines.append("| %s | %s | %s | %s | %s |" % (c["slug"], c.get("verdict"), c.get("iterations"), c.get("branch"), note))
    lines += ["", "## Merge plan", "", "```bash", "git checkout %s" % (gitutil.git(root, "rev-parse", "--abbrev-ref", "HEAD").strip() or "main")]
    lines += ["git merge --no-ff %s" % c["branch"] for c in f["children"] if c["status"] == "COMPLETE"]
    lines += ["```", "", "Siblings are isolated: merging PASS branches does not prove they integrate with each other. Run the suite after merging.", ""]
    blocked = [c for c in f["children"] if c["status"] == "BLOCKED"]
    if blocked:
        lines += ["## Blocked", ""]
        for c in blocked:
            bm = os.path.join(c["worktree"], ".happysquad", "runs", c["run_id"] or "", "BLOCKED.md")
            lines.append("- %s — cause %s — %s" % (c["slug"], c.get("cause"), bm))
    S.atomic_write(os.path.join(fleet_dir(root, fid), "aggregate-report.md"), "\n".join(lines) + "\n")


def cleanup(root, fid, cfg, keep_failed=True):
    f = load(root, fid)
    removed = []
    for c in f["children"]:
        if not c.get("worktree") or not os.path.isdir(c["worktree"]):
            continue
        if keep_failed and c["status"] != "COMPLETE":
            continue
        subprocess.run(["git", "worktree", "remove", "--force", c["worktree"]], cwd=root, capture_output=True)
        shutil.rmtree(c["worktree"], ignore_errors=True)
        removed.append(c["slug"])
    gitutil.git(root, "worktree", "prune", check=False)
    return {"action": "fleet", "fleet_id": fid, "removed": removed}
