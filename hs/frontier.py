"""Tracker frontier (spec §12, 1.1): read the ready-to-dispatch slice of an issue tracker and mark
tickets `squad:passed` when their fleet child completes. Never closes an issue — the user owns that.

Tracker type comes from `docs/agents/issue-tracker.md` (`type: local|github|gitlab`); absent or
unparseable → tracker "none". See `read()` for the per-tracker ticket/frontier shape.
"""
import glob
import json
import os
import re
import subprocess

from . import state as S

DONE_STATUSES = ("done", "closed", "squad:passed")


def _run(argv, cwd):
    try:
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(argv, 1, "", str(e))


def _tracker_type(root):
    p = os.path.join(root, "docs", "agents", "issue-tracker.md")
    if not os.path.isfile(p):
        return None
    m = re.search(r"^\s*type:\s*(\S+)", open(p).read(), re.I | re.M)
    t = m.group(1).strip().lower() if m else None
    return t if t in ("local", "github", "gitlab") else None


def _no_tracker():
    return {"tracker": "none", "tickets": [], "frontier": [], "note": "no issue tracker configured (docs/agents/issue-tracker.md)"}


# --- local -------------------------------------------------------------------

def _parse_blocked_by(text):
    m = re.search(r"^\s*Blocked by:\s*(.+)$", text, re.I | re.M)
    if not m:
        return []
    raw = m.group(1).strip()
    if not raw or raw.lower() == "none":
        return []
    return [tok.strip() for tok in raw.split(",") if tok.strip()]


def _read_local(root):
    paths = sorted(glob.glob(os.path.join(root, ".scratch", "*", "issues", "*.md")))
    tickets, by_id = [], {}
    for p in paths:
        text = open(p).read()
        title_m = re.search(r"^#\s+(.+)$", text, re.M)
        status_m = re.search(r"^\s*Status:\s*(.+)$", text, re.I | re.M)
        task_m = re.search(r"\*\*What to build:\*\*\s*\n?(.*?)(?:\n\s*\n|\n\*\*|\Z)", text, re.S)
        squad_passed = bool(re.search(r"^\s*Labels:.*squad:passed", text, re.I | re.M) or
                            re.search(r"^\s*squad:passed\s*$", text, re.I | re.M))
        t = {"ref": os.path.relpath(p, root).replace(os.sep, "/"),
             "title": title_m.group(1).strip() if title_m else None,
             "task": task_m.group(1).strip() if task_m else None,
             "blocked_by": _parse_blocked_by(text),
             "status": status_m.group(1).strip() if status_m else None,
             "squad_passed": squad_passed}
        tickets.append(t)
        by_id[os.path.splitext(os.path.basename(p))[0]] = t

    def _done(tok):
        other = by_id.get(tok.lstrip("#").strip())
        if not other:
            return False
        return other["squad_passed"] or (other["status"] or "").strip().lower() in DONE_STATUSES

    frontier = [t for t in tickets if (t["status"] or "").strip().lower() == "ready-for-agent"
               and not t["squad_passed"] and all(_done(b) for b in t["blocked_by"])]
    return {"tracker": "local", "tickets": tickets, "frontier": frontier, "note": None}


def _mark_passed_local(root, ref):
    p = os.path.join(root, ref)
    text = open(p).read()
    if re.search(r"^\s*Labels:.*squad:passed", text, re.I | re.M):
        return
    if re.search(r"^\s*Labels:", text, re.I | re.M):
        text = re.sub(r"^(\s*Labels:.*)$", lambda m: m.group(1).rstrip() + ", squad:passed", text, count=1, flags=re.I | re.M)
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += "Labels: squad:passed\n"
    S.atomic_write(p, text)


# --- github --------------------------------------------------------------------

_label_ensured = False


def _ensure_github_label(root):
    global _label_ensured
    if not _label_ensured:
        _run(["gh", "label", "create", "squad:passed", "--color", "0E8A16", "--force"], root)
        _label_ensured = True


def _read_github(root):
    r = _run(["gh", "issue", "list", "--label", "ready-for-agent", "--state", "open",
             "--json", "number,title,body,labels", "--limit", "100"], root)
    if r.returncode != 0:
        return {"tracker": "github", "tickets": [], "frontier": [], "note": "gh issue list failed: %s" % (r.stderr or r.stdout).strip()[:200]}
    try:
        issues = json.loads(r.stdout or "[]")
    except ValueError:
        return {"tracker": "github", "tickets": [], "frontier": [], "note": "gh issue list returned invalid JSON"}
    tickets = []
    for it in issues:
        if "squad:passed" in [l.get("name") for l in it.get("labels") or []]:
            continue  # dropped from the list entirely — already done
        tickets.append({"ref": "#%d" % it["number"], "title": it.get("title"),
                        "task": (it.get("body") or "").strip(), "blocked_by": _parse_blocked_by(it.get("body") or ""),
                        "status": "ready-for-agent", "squad_passed": False})
    cache = {}

    def _blocker_done(tok):
        n = tok.lstrip("#").strip()
        if n not in cache:
            r2 = _run(["gh", "issue", "view", n, "--json", "state,labels"], root)
            done = False
            if r2.returncode == 0:
                try:
                    data = json.loads(r2.stdout)
                    done = data.get("state") == "CLOSED" or "squad:passed" in [l.get("name") for l in data.get("labels") or []]
                except ValueError:
                    pass
            cache[n] = done
        return cache[n]

    frontier = [t for t in tickets if all(_blocker_done(b) for b in t["blocked_by"])]
    return {"tracker": "github", "tickets": tickets, "frontier": frontier, "note": None}


# --- gitlab (best-effort) -------------------------------------------------------

def _read_gitlab(root):
    r = _run(["glab", "issue", "list", "--label", "ready-for-agent", "--output", "json"], root)
    if r.returncode != 0:
        return {"tracker": "gitlab", "tickets": [], "frontier": [], "note": "glab issue list failed: %s" % (r.stderr or r.stdout).strip()[:200]}
    try:
        issues = json.loads(r.stdout or "[]")
    except ValueError:
        return {"tracker": "gitlab", "tickets": [], "frontier": [], "note": "glab issue list returned invalid JSON"}
    tickets = []
    for it in issues:
        if "squad:passed" in (it.get("labels") or []):
            continue
        body = it.get("description") or ""
        tickets.append({"ref": "#%s" % it.get("iid"), "title": it.get("title"), "task": body.strip(),
                        "blocked_by": _parse_blocked_by(body), "status": "ready-for-agent", "squad_passed": False})
    cache = {}

    def _blocker_done(tok):
        n = tok.lstrip("#").strip()
        if n not in cache:
            r2 = _run(["glab", "issue", "view", n, "--output", "json"], root)
            done = False
            if r2.returncode == 0:
                try:
                    data = json.loads(r2.stdout)
                    done = data.get("state") == "closed" or "squad:passed" in (data.get("labels") or [])
                except ValueError:
                    pass
            cache[n] = done
        return cache[n]

    frontier = [t for t in tickets if all(_blocker_done(b) for b in t["blocked_by"])]
    return {"tracker": "gitlab", "tickets": tickets, "frontier": frontier, "note": None}


# --- public ----------------------------------------------------------------------

def read(root):
    t = _tracker_type(root)
    if t == "local":
        return _read_local(root)
    if t == "github":
        return _read_github(root)
    if t == "gitlab":
        return _read_gitlab(root)
    return _no_tracker()


def mark_passed(root, ref):
    """Mark a ticket done. Never closes it — the user owns close/merge timing."""
    t = _tracker_type(root)
    if t == "local":
        _mark_passed_local(root, ref)
    elif t == "github":
        _ensure_github_label(root)
        _run(["gh", "issue", "edit", ref.lstrip("#"), "--add-label", "squad:passed"], root)
    elif t == "gitlab":
        _run(["glab", "issue", "update", ref.lstrip("#"), "--label", "squad:passed"], root)
