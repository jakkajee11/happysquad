---
description: Run multiple independent happysquad-loop tasks in parallel, each in its own git worktree and branch. Useful for processing a backlog of unrelated features quickly.
argument-hint: <tasks-file-path | --max=N | (interactive)>
---

Load the `fleet-orchestrator` skill at `${CLAUDE_PLUGIN_ROOT}/skills/fleet-orchestrator/SKILL.md` and run the fleet protocol.

Steps:

1. Parse `$ARGUMENTS`:
   - If it contains `--max=N`, extract N as the concurrency cap.
   - If `docs/agents/issue-tracker.md` exists (Matt Pocock skills configured), read the **tracker frontier** (open `ready-for-agent` tickets with no open blockers) as the task set — see the skill's "Tracker frontier mode". Each ticket is one child. Skip to step 3 unless the frontier is empty.
   - Else if `$ARGUMENTS` contains a file path, read newline-separated tasks from that file.
   - Otherwise treat the rest as a single task description and ask the user how many additional tasks to add.
2. If no tasks were resolved (no tracker, empty frontier, no file), use AskUserQuestion to gather them — ask first for the count (1-10), then for each task in turn.
3. Generate `fleet_id` = `YYYYMMDD-HHMMSS-<slug>` where slug is a short summary of the fleet's purpose (or the first task's first words if no overall purpose).
4. If `.happysquad/stack-profile.md` is missing, invoke the `stack-detector` skill once at the fleet root before any child runs.
5. Create `.happysquad/fleets/<fleet_id>/`, write `tasks.md`, initialize `fleet.json`.
6. Create one git worktree per task per the skill's Worktree creation rules. Base branch defaults to `main` (or whatever the current branch is if `main` doesn't exist).
7. Dispatch up to `max_parallel` children (default 4) **in a single message with multiple Agent tool calls**. Each child Agent invocation runs `/happysquad-loop` with the task as arguments and the worktree path as the working directory.
8. As children complete, update `fleet.json` and dispatch the next pending child to maintain `max_parallel` in flight. Don't exceed the cap.
9. When all children resolve (PASS / BLOCKED / FAIL), write the aggregate report per the skill template and offer:
   - Wiki ingest for PASS children (one at a time, never parallel — wiki writes share `knowledge/wiki/index.md`)
   - Worktree cleanup (yes / no / keep-failed-only)
10. Report a single concise summary back to the user with the fleet-id, pass/block counts, suggested merge commands, and pointers to BLOCKED.md files for any failed children.

Never auto-merge children's branches to main. Never delete worktrees without asking. Never exceed `max_parallel`.

If a child returns BLOCKED, the fleet keeps going — surface the BLOCK in the aggregate report. Other independent tasks should not be held up.

For interrupted fleets (the user re-runs `/squad-fleet` while a previous one is in progress), follow the skill's Resuming protocol — ask the user to resume, abort, or check status.
