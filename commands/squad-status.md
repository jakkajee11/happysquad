---
description: Show the happysquad's current state — active run, last agent, iteration count, reviewer verdicts so far, files touched, and what's recommended next.
---

Report a concise status of any active happysquad work — stack profile, dev-loop runs, brainstorm sessions, fleet runs, and wiki health.

Steps:

1. Look for `.happysquad/stack-profile.md`, `.happysquad/state.json` (dev-loop runs), any `.happysquad/brainstorms/*/session.json` (brainstorm sessions), any `.happysquad/fleets/*/fleet.json` (fleet runs), and `.happysquad/team-plan.json` (team-assembly plan). If `team-plan.json` exists, report a one-line callout near the top: its `approved` flag and, when approved, `approved_at` (e.g. "Team plan: approved" / "Team plan: pending approval — run /squad-assemble to review").
2. If none exist, say "No happysquad activity on record. Start with /squad-detect to scan the stack, or /brainstorm / /happysquad-loop / /squad-fleet." Stop.
   If in-progress work exists in any mode, mention at the top: "Resume any of these with /squad-resume." (State persists across sessions — closing and reopening does not lose progress.)
3. **Stack section** (only if `stack-profile.md` exists):
   - Primary stack one-liner (read from the Summary section of stack-profile.md)
   - Detector version + generated date
   - Skill recommendation counts per agent (e.g. "architecter: 3, implementer: 2, …")
   - Gaps count (number of capabilities with no installed skill)
   - Whether any manifest is newer than the profile (suggest `/squad-detect` to refresh if yes)
4. **Dev-loop section** (only if state.json exists):
   - Active task (first line of `task` field)
   - Run-id, `mode` (single / parallel / fleet-child), and `worktree` path if any
   - Current state and iteration N of cap
   - Started_at and updated_at (humanized: "12 minutes ago")
   - Workstream table (parallel mode only): name, owned_files count, implement_status, test_status, depends_on
   - History table — one row per state transition, columns: iteration, state, agent(s), result, route (for review rows only). Parallel waves get one row with all workstreams listed.
   - Last reviewer verdict and route (if any) — plus workstream targets when parallel
   - Conflict-check status: CLEAN / VIOLATIONS / pending
   - Files changed so far (`git diff --name-only` against the merge base, or against `HEAD` if no merge base detected)
   - Next recommended command (e.g. "Continue with /happysquad-loop to resume", "Run /squad-implement to address feedback", "Run nothing — loop is COMPLETE")
   - If `current_state` is `BLOCKED`, also show the top 3 blocking issues from the most recent review.md.

5. **Fleet section** (only if any fleet.json exists with status != complete or was the most recently updated):
   - Fleet ID, started_at
   - Total tasks, currently running, completed (PASS / BLOCKED / FAIL)
   - Per-task one-liner: slug, status, iteration, branch
   - Worktree directory location
   - Next recommended action (e.g. "Run /squad-fleet to resume", "All complete — review aggregate-report.md", "K BLOCKED tasks — inspect their BLOCKED.md")
6. **Brainstorm section** (only if any brainstorm session is in_progress or was the most recently updated):
   - Session ID and topic
   - Current round (1 / 2 / 3)
   - Agents that have completed the current round vs still pending
   - If status is `complete`, show the convergence verdict (full-consensus / minor-dissent / major-dissent) and DISSENT count
   - Pointer to `consensus.md` if it exists
   - Next recommended command (e.g. "Continue with /brainstorm to resume", "Proceed to /happysquad-loop", or "Review consensus.md before deciding")
7. **Wiki section** (only if `knowledge/wiki/index.md` exists):
   - Article count by topic (decisions/N, lessons/N, patterns/N, runbook/N, subsystems/N)
   - Most recent ingest (from the last entry in `knowledge/wiki/log.md`)
   - One-line health note: "lint clean" / "N pending lint findings" / "lint not run recently"
8. Keep total output under 60 lines. Detail lives on disk; don't duplicate it.
