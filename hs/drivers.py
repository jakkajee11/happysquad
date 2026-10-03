"""Drivers (spec §11): headless (hs drives `claude -p` itself) and fake (same path, fake binary).

The agent-tool driver is the LLM orchestrator following skills/hs-loop; it needs nothing here.
"""
import json
import os
import shutil
import subprocess
import sys
import time

from . import config as C, gitutil, machine, state as S

PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# --- agent definition → --agents JSON ---------------------------------------

def _frontmatter(path):
    text = open(path).read()
    if not text.startswith("---"):
        return {}, text
    head, _, body = text[3:].partition("\n---")
    meta = {}
    cur = None
    for line in head.splitlines():
        if not line.strip():
            continue
        if line.startswith("  ") and cur:
            meta[cur] = (meta[cur] + "\n" + line.strip()).strip()
        elif ":" in line:
            k, _, v = line.partition(":")
            cur = k.strip()
            meta[cur] = v.strip().strip("|").strip()
    return meta, body.lstrip("\n")


def agents_json(agent):
    """Build the `--agents` object for one agent from agents/<agent>.md (name, description, prompt, tools, model)."""
    path = os.path.join(PLUGIN_ROOT, "agents", "%s.md" % agent)
    meta, body = _frontmatter(path)
    tools = [t.strip() for t in meta.get("tools", "").split(",") if t.strip()]
    spec = {"description": (meta.get("description") or agent).splitlines()[0][:200], "prompt": body}
    if tools:
        spec["tools"] = tools
    if meta.get("model"):
        spec["model"] = meta["model"]
    return {agent: spec}


def claude_argv(agent, model, prompt_text, cfg, out_file=None):
    """Pure: the argv for one headless dispatch. Unit-tested without invoking anything."""
    h = cfg.get("headless", {})
    binary = os.environ.get("HS_CLAUDE") or "claude"
    argv = [binary, "-p", prompt_text,
            "--agents", json.dumps(agents_json(agent)), "--agent", agent,
            "--model", model,
            "--permission-mode", "acceptEdits",
            "--allowedTools", h.get("allowed_tools", "Read,Write,Edit,Grep,Glob,Bash"),
            "--max-budget-usd", str(h.get("budget_per_phase", 2.0)),
            "--output-format", "json"]
    for t in h.get("disallowed_tools", []):
        argv += ["--disallowedTools", t]
    return argv


# --- worktree isolation ----------------------------------------------------------

def isolate(root, run_id):
    """Create the run's worktree (spec §11, Q2) and return its path; the run lives there."""
    wt = os.path.join(gitutil.common_dir(root), "happysquad", "wt", run_id)
    branch = "hs/%s" % run_id
    if not os.path.isdir(wt):
        gitutil.git(root, "worktree", "add", "-q", "-b", branch, wt, "HEAD")
        # the run's config/profile travel with it (gitignored in the main tree)
        src = os.path.join(root, ".happysquad")
        dst = os.path.join(wt, ".happysquad")
        os.makedirs(dst, exist_ok=True)
        for name in ("config.json", "stack-profile.md", "stack-profile.json", "risk-patterns.json", ".gitignore"):
            p = os.path.join(src, name)
            if os.path.isfile(p):
                shutil.copy(p, os.path.join(dst, name))
    return wt, branch


# --- the headless loop -------------------------------------------------------------

def _run_one(root, d, cfg, log_dir):
    prompt = open(os.path.join(root, d["prompt_file"])).read()
    argv = claude_argv(d["agent"], d["model"], prompt, cfg, d["out_file"])
    env = dict(os.environ, HS_CHILD="1")
    log = os.path.join(root, log_dir, "claude-%s.jsonl" % os.path.basename(os.path.dirname(d["out_file"])))
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, "w") as lf:
        p = subprocess.Popen(argv, cwd=root, stdout=lf, stderr=subprocess.STDOUT, env=env, start_new_session=True)
    return p


def run_headless(root, task, cfg, lite=False, max_parallel=None, isolate_wt=None):
    """Drive a whole run to done. Returns the final action dict."""
    rid_root = root
    use_wt = (isolate_wt if isolate_wt is not None else cfg.get("headless", {}).get("isolate", "worktree")) == "worktree"
    act = machine.start(root, task, cfg, lite=lite, driver="headless")
    if act.get("action") == "error":
        return act
    rid = S.current_run_id(root)
    if use_wt:
        wt, branch = isolate(root, rid)
        # move the run directory into the worktree so every path is worktree-relative
        src = S.run_dir(root, rid)
        dst = S.run_dir(wt, rid)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        S.set_current(wt, rid)
        st = S.load_state(dst)
        st["worktree"] = wt
        st["branch"] = branch
        S.save_state(dst, st)
        root = wt
        cfg = C.load(root)
        S.append_event(dst, "isolate", data={"worktree": wt, "branch": branch})
    cap = max_parallel or cfg.get("max_parallel", 4)
    procs = {}
    while True:
        act = machine.next_action(root, rid, cfg)
        a = act.get("action")
        if a in ("dispatch", "dispatch_many") and act.get("_specs"):
            act = machine.dispatch(root, rid, cfg)
            a = act.get("action")
        if a == "done":
            break
        if a == "error":
            break
        if a == "advance":
            machine.advance(root, rid, cfg)
            continue
        if a == "ask":
            machine.answer(root, rid, cfg, act["key"], act["default"])
            continue
        if a in ("dispatch", "dispatch_many"):
            ds = act["dispatches"] if a == "dispatch_many" else [act]
            for d in ds:
                while len([p for p in procs.values() if p.poll() is None]) >= cap:
                    time.sleep(2)
                procs[d["out_file"]] = _run_one(root, d, cfg, os.path.join(".happysquad", "runs", rid, "logs"))
            continue
        if a == "wait":
            files = act["files"]
            # reap finished children; a child that exited without writing out.json is an agent error
            for f in files:
                p = procs.get(f)
                if p is not None and p.poll() is not None and not os.path.isfile(os.path.join(root, f)):
                    rc = p.returncode
                    S.append_event(S.run_dir(root, rid), "agent.error", data={"out_file": f, "rc": rc})
                    procs.pop(f, None)
                    # one retry: re-dispatch via resume's quiet path by forcing the pending entry stale
                    st = S.load_state(S.run_dir(root, rid))
                    retried = st.setdefault("agent_retries", {})
                    if retried.get(f, 0) >= 1:
                        machine.block_manual(root, rid, cfg, "agent", "headless agent exited rc=%s twice without output: %s" % (rc, f))
                        break
                    retried[f] = retried.get(f, 0) + 1
                    S.save_state(S.run_dir(root, rid), st)
                    for pend in st.get("pending", []):
                        if pend["out_file"] == f:
                            pend["dispatched_at"] = "2000-01-01T00:00:00Z"
                    S.save_state(S.run_dir(root, rid), st)
                    machine.resume(root, rid, cfg)
            if any(os.path.isfile(os.path.join(root, f)) for f in files):
                machine.advance(root, rid, cfg)
                continue
            time.sleep(cfg.get("headless", {}).get("poll_interval", 3))
            continue
        break
    final = machine.next_action(root, rid, cfg)
    final.pop("_specs", None)
    if use_wt:
        final["worktree"] = root
        final["branch"] = branch
        final["suggested_merge"] = "git merge --no-ff %s" % branch
    return final
