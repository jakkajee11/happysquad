"""Drivers (spec §11): headless (hs drives `claude -p` itself) and fake (same path, fake binary).

The agent-tool driver is the LLM orchestrator following skills/hs-loop; it needs nothing here.
"""
import json
import os
import shutil
import signal
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


ROLE_PROMPTS = {
    # Headless agents get a short role prompt; the rendered dispatch prompt (prompts/*.md) carries the
    # contract. The 0.16 agents/*.md bodies are NOT used here: they describe marker lines, brainstorm
    # modes and artifact paths that contradict the hs contract (seen in the first headless smoke: the
    # architecter printed DESIGN_READY and wrote progress.md instead of out.json).
    "architecter": "You design before code exists. Read the repo first; never invent paths. Produce exactly the artifacts the task prompt names and nothing else. Do not write code, run builds or tests, or commit; Bash is for the validate command only.",
    "implementer": "You turn a design into working code inside the files you own. Match the repo's conventions. Run the build yourself. No new test files, no commits, no edits outside owned files.",
    "tester": "You write and run tests that pin the acceptance criteria. Assert specific values; for cancel/delete/lookup assert against ids the test itself created. Never modify production code.",
    "reviewer": "You are the chief reviewer: read the whole diff yourself, cite file:line for every finding, give each a verify command or `manual`, never edit code, never emit a verdict (the engine computes it).",
    "specialist": "You review exactly one axis against its checklist. Concrete mechanism and file:line per finding; out-of-scope notes go in the report only. Never edit code.",
}


def agent_file(agent):
    """The v1 agent file (agents/hs-<agent>.md) when present, else the 0.16 one (agents/<agent>.md)."""
    for name in ("hs-%s.md" % agent, "%s.md" % agent):
        p = os.path.join(PLUGIN_ROOT, "agents", name)
        if os.path.isfile(p):
            return p, name.startswith("hs-")
    return None, False


def agents_json(agent):
    """Build the `--agents` object for one agent.

    With a v1 file (agents/hs-<agent>.md) its body is the system prompt and its frontmatter the
    tools/model. With only a 0.16 file, use its frontmatter tools but a short ROLE_PROMPTS entry,
    because the 0.16 body contradicts the hs contract.
    """
    path, is_v1 = agent_file(agent)
    meta, body = _frontmatter(path) if path else ({}, "")
    tools = [t.strip() for t in meta.get("tools", "").split(",") if t.strip()]
    if agent == "specialist" and not tools:
        tools = ["Read", "Grep", "Glob", "Bash", "Write"]
    if agent in ("reviewer", "specialist") and "Write" not in tools:
        tools.append("Write")  # review.md / out.json must be writable (0.16 frontmatter omits it)
    spec = {"description": (meta.get("description") or agent).splitlines()[0][:200],
            "prompt": body.strip() if (is_v1 and body.strip()) else ROLE_PROMPTS.get(agent, "You are the %s." % agent)}
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

def worktree_base(root):
    """Where isolated run worktrees live: a sibling dir of the repo, never under .git/.

    Claude Code treats any path containing a `.git/` segment as a sensitive file and refuses
    every Write/Edit/Bash redirect into it, so a worktree under <git-common-dir> is unusable
    by agents. `config.headless.worktree_dir` overrides (absolute or repo-relative).
    """
    cfg_dir = (C.load(root).get("headless") or {}).get("worktree_dir")
    if cfg_dir:
        return cfg_dir if os.path.isabs(cfg_dir) else os.path.join(root, cfg_dir)
    top = gitutil.git(root, "rev-parse", "--show-toplevel").strip()
    return os.path.join(os.path.dirname(top), os.path.basename(top) + "-hs-wt")


def isolate(root, run_id):
    """Create the run's worktree (spec §11, Q2) and return its path; the run lives there."""
    wt = os.path.join(worktree_base(root), run_id)
    branch = "hs/%s" % run_id
    if not os.path.isdir(wt):
        os.makedirs(os.path.dirname(wt), exist_ok=True)
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

def agent_timeout(cfg, agent):
    """Seconds a headless agent may run. config.headless.agent_timeout is minutes by agent name; a project
    value replaces the dict whole (one-level merge), so fall back to its "default", then the built-in one."""
    user = (cfg.get("headless") or {}).get("agent_timeout") or {}
    base = C.DEFAULTS["headless"]["agent_timeout"]
    mins = user.get(agent, user.get("default", base.get(agent, base["default"])))
    return int(float(mins) * 60)

def _run_one(root, d, cfg, log_dir):
    prompt = open(os.path.join(root, d["prompt_file"])).read()
    argv = claude_argv(d["agent"], d["model"], prompt, cfg, d["out_file"])
    env = dict(os.environ, HS_CHILD="1")
    log = os.path.join(root, log_dir, "claude-%s.jsonl" % os.path.basename(os.path.dirname(d["out_file"])))
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, "w") as lf:
        p = subprocess.Popen(argv, cwd=root, stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT,
                             env=env, start_new_session=True)
    p.hs_deadline = time.time() + agent_timeout(cfg, d["agent"])
    p.hs_log = log
    return p

def _agent_of(st, out_file):
    return next((p["agent"] for p in st.get("pending", []) if p["out_file"] == out_file), "default")

def _kill_overdue(procs, root, rid):
    """Kill every child past its deadline (whole process group); log an agent.timeout event for each.

    The killed child then has no out.json, so the wait loop treats it like any agent that exited
    without output: one retry, then BLOCKED cause=agent.
    """
    now = time.time()
    for f, p in procs.items():
        if p.poll() is None and now > getattr(p, "hs_deadline", float("inf")):
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            p.wait()
            S.append_event(S.run_dir(root, rid), "agent.timeout", data={"out_file": f, "rc": p.returncode})


def drive_existing(root, rid, cfg):
    """Drive an already-started run (e.g. review-only) to done, in place."""
    return _drive(root, rid, cfg, use_wt=False, branch=None)


def run_headless(root, task, cfg, lite=False, max_parallel=None, isolate_wt=None):
    """Drive a whole run to done. Returns the final action dict."""
    use_wt = (isolate_wt if isolate_wt is not None else cfg.get("headless", {}).get("isolate", "worktree")) == "worktree"
    act = machine.start(root, task, cfg, lite=lite, driver="headless")
    if act.get("action") == "error":
        return act
    rid = S.current_run_id(root)
    branch = None
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
    return _drive(root, rid, cfg, use_wt=use_wt, branch=branch, max_parallel=max_parallel)


def _drive(root, rid, cfg, use_wt=False, branch=None, max_parallel=None):
    """The headless action loop for run `rid` rooted at `root` (worktree or in place)."""
    cap = max_parallel or cfg.get("max_parallel", 4)
    procs = {}
    poll = cfg.get("headless", {}).get("poll_interval", 3)
    events_path = os.path.join(S.run_dir(root, rid), "events.jsonl")

    def _nev():
        try:
            return sum(1 for _ in open(events_path))
        except OSError:
            return 0

    idle = 0
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
            # an agent writes out.json mid-turn; its log's result line (cost_usd) lands only at exit.
            # Consume after the child exits so the consume event can read it. Bounded by agent_timeout.
            live = [p for p in procs.values() if p.poll() is None]
            if live and any(os.path.isfile(os.path.join(root, f)) and procs[f].poll() is None for f in procs):
                _kill_overdue(procs, root, rid)
                time.sleep(min(poll, 1))
                continue
            before = _nev()
            machine.advance(root, rid, cfg)
            if _nev() == before:
                # no event means no progress; never spin on the engine
                idle += 1
                if idle >= 20:
                    machine.block_manual(root, rid, cfg, "engine",
                                         "driver made no progress after %d advance calls (%s)" % (idle, act.get("reason")))
                    break
                time.sleep(poll)
            else:
                idle = 0
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
            idle = 0
            _kill_overdue(procs, root, rid)
            # a pending entry with no child process (re-dispatch after heal/resume) must be launched
            for d in act.get("dispatches", []):
                if d["out_file"] not in procs and not os.path.isfile(os.path.join(root, d["out_file"])):
                    while len([p for p in procs.values() if p.poll() is None]) >= cap:
                        time.sleep(2)
                    procs[d["out_file"]] = _run_one(root, d, cfg, os.path.join(".happysquad", "runs", rid, "logs"))
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
                        why = ("timed out twice (config.headless.agent_timeout: %d min)" % (agent_timeout(cfg, _agent_of(st, f)) // 60)
                               if getattr(p, "hs_deadline", float("inf")) < time.time() else "exited rc=%s twice without output" % rc)
                        machine.block_manual(root, rid, cfg, "agent", "headless agent %s: %s" % (why, f))
                        break
                    retried[f] = retried.get(f, 0) + 1
                    S.save_state(S.run_dir(root, rid), st)
                    for pend in st.get("pending", []):
                        if pend["out_file"] == f:
                            pend["dispatched_at"] = "2000-01-01T00:00:00Z"
                    S.save_state(S.run_dir(root, rid), st)
                    machine.resume(root, rid, cfg)
            # advance only once a landed out.json's agent has exited: the agent writes out.json mid-turn,
            # and its log's result line (cost_usd) only lands at exit — consume reads it from there
            landed = [f for f in files if os.path.isfile(os.path.join(root, f))]
            if landed and all(procs.get(f) is None or procs[f].poll() is not None for f in landed):
                machine.advance(root, rid, cfg)
                continue
            time.sleep(poll)
            continue
        break
    final = machine.next_action(root, rid, cfg)
    final.pop("_specs", None)
    if use_wt:
        final["worktree"] = root
        final["branch"] = branch
        final["suggested_merge"] = "git merge --no-ff %s" % branch
    return final
