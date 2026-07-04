#!/usr/bin/env bash
# happysquad SessionStart hook.
# In any project that has a ./.happysquad dir, prints a compact orientation block:
#   1. git snapshot — recent commits + working-tree status
#   2. DRIFT warning — when an active happysquad run has fallen behind git
#      (a commit landed after the loop last updated → likely direct work bypassed it)
#   3. resume anchor — tail of .happysquad/progress.md if present.
#      NOTE: .happysquad/progress.md is LOCAL/personal — the standard happysquad .gitignore
#      ignores .happysquad/* (except config.json + stack-profile.*), so this file is NOT
#      committed and is NOT shared with teammates. For a SHARED roadmap, keep a tracked file
#      such as root PROGRESS.md and @import it into CLAUDE.md instead. (To share THIS file,
#      add an exception to .gitignore: !/.happysquad/progress.md)
#   4. resume nudge — in-progress dev-loop / brainstorm / fleet state
# Also records the session-start HEAD and clears the Stop hook's one-shot marker.
# Prints NOTHING outside a happysquad project (zero context cost). Never fails the session.
set -u

HAPPYSQUAD_DIR=".happysquad"

# No happysquad state in this project → nothing to do (keeps non-happysquad projects silent).
[ -d "$HAPPYSQUAD_DIR" ] || exit 0

# ---------------------------------------------------------------------------
# git snapshot + drift + session bookkeeping (only inside a git work tree)
# ---------------------------------------------------------------------------
if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git rev-parse HEAD > "$HAPPYSQUAD_DIR/.session-head" 2>/dev/null || true
  rm -f "$HAPPYSQUAD_DIR/.sync-nudged" 2>/dev/null || true

  echo "[happysquad] git snapshot"
  git log -3 --format='%h %s' 2>/dev/null | sed 's/^/  · /'
  dirty=$(git status --porcelain 2>/dev/null | grep -c .)
  if [ "${dirty:-0}" -gt 0 ]; then
    echo "  tree: ${dirty} uncommitted change(s) — see git status"
  else
    echo "  tree: clean"
  fi

  if command -v python3 >/dev/null 2>&1; then
    python3 - <<'PY' 2>/dev/null || true
import json, subprocess, datetime
try:
    d = json.load(open(".happysquad/state.json"))
except Exception:
    raise SystemExit
st = d.get("current_state")
if st in (None, "COMPLETE", "BLOCKED"):
    raise SystemExit
ua = d.get("updated_at")
if not ua:
    raise SystemExit
try:
    head = subprocess.check_output(["git", "log", "-1", "--format=%cI"], text=True).strip()
    def p(s): return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    if p(head) > p(ua):
        task = str(d.get("task", "?")).splitlines()[0][:60]
        print(f'  ⚠ DRIFT: happysquad run is at {st} (iter {d.get("iteration","?")}) for "{task}",')
        print('    but a commit landed after it last updated — likely direct work bypassed the loop.')
        print('    Reconcile: /squad-status, then /squad-resume or mark the run done.')
except Exception:
    pass
PY
  fi

  # Local/personal scratch anchor (gitignored, NOT shared — see header note).
  # A shared roadmap should live in a tracked file (e.g. root PROGRESS.md) instead.
  if [ -f "$HAPPYSQUAD_DIR/progress.md" ]; then
    echo "[happysquad] .happysquad/progress.md (local scratch — not committed/shared) — tail:"
    tail -n 8 "$HAPPYSQUAD_DIR/progress.md" 2>/dev/null | sed 's/^/  /'
  fi
fi

# ---------------------------------------------------------------------------
# in-progress happysquad work nudge (original behavior, unchanged)
# ---------------------------------------------------------------------------
command -v python3 >/dev/null 2>&1 || exit 0

python3 - "$HAPPYSQUAD_DIR" <<'PYEOF' 2>/dev/null || exit 0
import json, os, sys, glob

base = sys.argv[1]
candidates = []

def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None

# dev-loop
d = load(os.path.join(base, "state.json"))
if d and d.get("current_state") not in ("COMPLETE", "BLOCKED", None):
    candidates.append((
        "dev-loop",
        d.get("task", "?"),
        f"state {d.get('current_state','?')}, iter {d.get('iteration','?')}",
        d.get("updated_at", ""),
    ))

# brainstorms
for f in glob.glob(os.path.join(base, "brainstorms", "*", "session.json")):
    d = load(f)
    if d and d.get("status") == "in_progress":
        candidates.append((
            "brainstorm",
            d.get("topic", "?"),
            f"round {d.get('current_round', '?')}",
            d.get("updated_at", ""),
        ))

# fleets
for f in glob.glob(os.path.join(base, "fleets", "*", "fleet.json")):
    d = load(f)
    if d and d.get("status") == "in_progress":
        running = sum(1 for t in d.get("tasks", []) if t.get("status") == "in_progress")
        pending = sum(1 for t in d.get("tasks", []) if t.get("status") == "pending")
        candidates.append((
            "fleet",
            d.get("fleet_id", "?"),
            f"{running} running, {pending} pending",
            d.get("updated_at", ""),
        ))

if not candidates:
    sys.exit(0)

# Most-recently-updated first.
candidates.sort(key=lambda c: c[3] or "", reverse=True)

lines = ["[happysquad] You have in-progress work that can be resumed:"]
for kind, what, where, _updated in candidates[:5]:
    what = str(what).replace("\n", " ").strip()
    short = (what[:60] + "...") if len(what) > 60 else what
    lines.append(f"  - [{kind}] {short} ({where})")
lines.append("Run /squad-resume to continue, or /squad-status for the full picture.")
print("\n".join(lines))
PYEOF

exit 0
