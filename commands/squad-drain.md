---
description: Continuously drain the tracker frontier — run ready-for-agent tickets one at a time (serial by default) through the full squad loop, pumping as blockers clear, until the frontier is empty. Frontier-only; pair with /loop for a standing watch.
argument-hint: [--max=N] [--no-pump]
---

Load the `fleet-orchestrator` skill at `${CLAUDE_PLUGIN_ROOT}/skills/fleet-orchestrator/SKILL.md` and run its **Drain mode** (see the "Drain mode (`/squad-drain`)" subsection). Drain is fleet's serial, non-interactive variant for working a tracker queue — it reuses all fleet machinery and only changes the entry, defaults, and empty/end handling so it is safe to wrap in `/loop`.

Steps:

1. Parse `$ARGUMENTS`:
   - `--max=N` → concurrency cap. **Default 1** (serial drain — one ticket at a time).
   - `--no-pump` → single snapshot pass. **Pumping is ON by default** in drain mode.
2. **Require a tracker.** If `docs/agents/issue-tracker.md` does not exist, print exactly one line — "drain requires an issue-tracker (Matt Pocock `/to-tickets`); none configured — use `/squad-fleet` for manual task lists." — and **stop**. Drain is frontier-only; never fall back to interactive/file/paste task sources.
3. **Collect the tracker frontier** per the skill's "Tracker frontier mode" (`ready-for-agent`, no open blockers, not `squad:passed`). If the frontier is **empty**, print one line — "Frontier empty — nothing to drain." — and **stop with success**. No prompt, no fallback (this keeps `/loop 5m /squad-drain` a cheap no-op on empty ticks).
4. If `.happysquad/stack-profile.md` is missing, invoke the `stack-detector` skill once at the repo root before any child runs.
5. Generate `fleet_id` = `YYYYMMDD-HHMMSS-drain-<slug>`, create `.happysquad/fleets/<fleet_id>/`, write `tasks.md`, and initialize `fleet.json` with `status: "in_progress"` and `mode: "drain"` (the `status` field is what `/squad-resume` and `/squad-status` key on).
6. Create one git worktree per frontier ticket per the skill's Worktree creation rules, and dispatch up to `--max` children (default 1) **via the Agent tool**, each running `/happysquad-loop` with the ticket's task as arguments and the worktree path as working directory.
7. As children complete, update `fleet.json`, **re-scan the frontier (pump)** unless `--no-pump`, and dispatch the next pending / newly-unblocked ticket to keep `--max` in flight. A `squad:passed` ticket is excluded from every re-scan. Repeat until the frontier is empty.
8. When the frontier drains, write the aggregate report per the skill template. **Do not** surface the interactive wiki-ingest or worktree-cleanup prompts (drain must not block on input) — instead print the merge commands, BLOCKED.md pointers, and a cleanup reminder as plain text for the user to act on outside the loop.

Never auto-merge children's branches to main. Never delete worktrees. Never exceed `--max`. A BLOCKED child does not stall the drain — surface it in the aggregate report and keep going.

For a standing watch, pair with the built-in loop: `/loop 5m /squad-drain` re-invokes drain on an interval — each tick drains the current frontier and exits, empty ticks are silent no-ops, and tickets added between ticks are picked up on the next tick.

For interrupted drains (the user re-runs `/squad-drain` while a previous one is in progress), follow the skill's Resuming protocol.
