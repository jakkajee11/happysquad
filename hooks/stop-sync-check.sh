#!/usr/bin/env bash
# happysquad Stop hook — at most ONE nudge per session.
# If source code changed this session (commits since session start, or a dirty tree) but no
# progress anchor (PROGRESS.md or .happysquad/progress.md) was updated, remind to journal it so
# the next session can resume. Exit 2 surfaces the reminder to the model; the one-shot marker
# (written here, cleared by the SessionStart hook) guarantees no loop. Silent outside a
# happysquad project. Never fails the session on error.
set -u

HAPPYSQUAD_DIR=".happysquad"
[ -d "$HAPPYSQUAD_DIR" ] || exit 0
command -v git >/dev/null 2>&1 || exit 0
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0
[ -f "$HAPPYSQUAD_DIR/.sync-nudged" ] && exit 0   # already nudged this session → never loop

start=$(cat "$HAPPYSQUAD_DIR/.session-head" 2>/dev/null || echo "")
head=$(git rev-parse HEAD 2>/dev/null || echo "")

committed=""
if [ -n "$start" ] && [ "$start" != "$head" ]; then
  committed=$(git diff --name-only "$start" "$head" 2>/dev/null)
fi
working=$(git status --porcelain 2>/dev/null | sed 's/^...//')
changed=$(printf '%s\n%s\n' "$committed" "$working" | grep -vE '^[[:space:]]*$' || true)
[ -z "$changed" ] && exit 0

# only source changes warrant a nudge; pure docs/config/journal churn does not
code=$(printf '%s\n' "$changed" | grep -E '\.(ts|tsx|js|jsx|mjs|cjs|css|prisma|py|go|rs|java|rb|php|c|cpp|h|swift|kt)$' || true)
[ -z "$code" ] && exit 0

# progress anchor already journaled this session? → fine
printf '%s\n' "$changed" | grep -qiE '(^|/)progress\.md$' && exit 0

touch "$HAPPYSQUAD_DIR/.sync-nudged" 2>/dev/null || true
echo "Sync reminder: source changed this session but no progress log was updated. Add a one-line entry to PROGRESS.md (or .happysquad/progress.md) — what changed / what's next — so the next session can resume, then finish." >&2
exit 2
