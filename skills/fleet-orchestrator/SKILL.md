---
name: fleet-orchestrator
description: |
  Runs multiple independent happysquad-loop tasks in parallel, each in its own git worktree on its own
  branch, so they cannot collide. Each fleet child is a normal /happysquad-loop with full
  architect → implement → test → review machinery. The fleet orchestrator schedules them,
  monitors completion, and aggregates results. Triggers: /squad-fleet, "run multiple tasks in parallel",
  "fleet mode", "process this backlog", "fan out across worktrees".
---

# Fleet Orchestrator

The happysquad's multi-task parallel mode. Spawn N independent `/happysquad-loop` runs across N git worktrees, each on its own branch, all running concurrently. Each child is a complete loop (with its own architecter / implementer / tester / reviewer iterations); the fleet orchestrator handles dispatch, monitoring, and roll-up.

Distinct from **within-task parallelism** (handled by the squad-loop skill's PARALLEL_IMPLEMENT state) — fleet mode parallelizes *across* tasks, not *within* one.

## When to use

| Situation                                                          | Use            |
|--------------------------------------------------------------------|----------------|
| One task with parts that can run side by side (backend + frontend) | squad-loop (parallel mode) |
| Several unrelated features in a backlog                            | fleet          |
| One feature touching multiple services / repos                     | fleet (one task per service) |
| Quick bug-fix sweep across the codebase                            | fleet          |

The break-even point: if tasks share files or designs, prefer in-task parallelism. If tasks are truly independent (different features, different layers, different goals), prefer fleet.

## Architecture

```
.happysquad/
├── fleets/
│   └── 20260520-103045-q2-features/        # one directory per fleet
│       ├── fleet.json                       # fleet-level state + child summaries
│       ├── tasks.md                         # input task list (verbatim)
│       └── aggregate-report.md              # final roll-up across all children
└── worktrees/
    └── 20260520-103045-q2-features/
        ├── add-export/                      # worktree for child 1 — on branch fleet/<fleet-id>/add-export
        │   └── .happysquad/runs/.../...      # child's normal run artifacts
        ├── update-billing/                   # worktree for child 2
        └── infra-bump/                       # worktree for child 3
```

Each worktree has its own `.happysquad/state.json` (with `mode: "fleet-child"` and `parent_fleet_id` set). The parent `fleet.json` tracks the cross-cutting view.

## fleet.json

```json
{
  "fleet_id": "20260520-103045-q2-features",
  "started_at": "2026-05-20T10:30:45Z",
  "updated_at": "2026-05-20T11:45:12Z",
  "status": "in_progress",
  "max_parallel": 4,
  "tasks": [
    {
      "slug": "add-export",
      "task": "let customers export their own data",
      "worktree": ".happysquad/worktrees/20260520-103045-q2-features/add-export",
      "branch": "fleet/20260520-103045-q2-features/add-export",
      "run_id": "20260520-103047-add-export",
      "status": "in_progress",
      "current_state": "PARALLEL_TEST",
      "iteration": 2
    },
    {
      "slug": "update-billing",
      "task": "switch billing to monthly proration",
      "worktree": ".happysquad/worktrees/20260520-103045-q2-features/update-billing",
      "branch": "fleet/20260520-103045-q2-features/update-billing",
      "run_id": "20260520-103048-update-billing",
      "status": "complete",
      "verdict": "PASS",
      "iteration": 3
    },
    {
      "slug": "infra-bump",
      "task": "upgrade EF Core to 9, .NET 9",
      "worktree": ".happysquad/worktrees/20260520-103045-q2-features/infra-bump",
      "branch": "fleet/20260520-103045-q2-features/infra-bump",
      "run_id": "20260520-103049-infra-bump",
      "status": "BLOCKED",
      "iteration": 5
    }
  ]
}
```

## Orchestration protocol

### Setup

1. Collect the task list. Sources, in order of preference:
   - File path passed in `$ARGUMENTS` (newline-separated tasks).
   - Pasted text via AskUserQuestion (the user types/pastes the list).
   - Interactive prompt: ask "How many tasks? Then I'll ask for each one."
2. Generate `fleet_id` = `YYYYMMDD-HHMMSS-<slug-of-fleet-purpose>`.
3. Create `.happysquad/fleets/<fleet_id>/` and write `tasks.md` (verbatim input).
4. Initialize `fleet.json` with `status: "in_progress"`, `max_parallel` from `.happysquad/config.json` (default 4 — limit to avoid overwhelming Claude Agent Team).

### Worktree creation

For each task:

1. Slug the task to ~30 chars kebab-case for the worktree directory name.
2. Determine the base branch (default `main`, or read from config).
3. Run: `git worktree add -b fleet/<fleet_id>/<slug> .happysquad/worktrees/<fleet_id>/<slug> <base-branch>`
4. Record the worktree path and branch in `fleet.json.tasks[i]`.

If worktree creation fails (branch exists, dirty index, etc.), surface to the user and stop. Don't proceed with a partial fleet — that's how you get half-finished runs.

### Concurrent dispatch

Respect `max_parallel`. The orchestrator runs at most N child loops concurrently:

1. Sort tasks (any order — they're independent by definition).
2. Dispatch the first `min(N, total_tasks)` children:
   - For each child, launch `/happysquad-loop` **via the Agent tool** with the worktree path passed as the working directory. Each child runs its own full state machine.
   - All child dispatches go in a single message with multiple Agent tool calls.
3. As children complete (the Agent tool returns), update `fleet.json` and immediately dispatch the next pending task to keep N children in flight.
4. Repeat until all tasks are `complete`, `BLOCKED`, or the fleet itself is aborted.

### Monitoring

After each child completes, the parent agent reads the child's `.happysquad/state.json` (inside the child's worktree) to get its final state, verdict, iteration count, and files-changed list. Write that into `fleet.json.tasks[i]`.

If a child returns BLOCKED, the fleet does NOT abort other children — they continue. BLOCKED children are surfaced in the aggregate report; the user decides how to handle each.

### Aggregate report

When `status` transitions to `complete` (all children resolved):

1. Write `.happysquad/fleets/<fleet_id>/aggregate-report.md`:

```markdown
# Fleet <fleet_id> — aggregate report

Started: <timestamp>
Ended: <timestamp>
Total tasks: N
Passed: P · Blocked: B · Failed: F

## Results

| Slug          | Verdict | Iterations | Files changed | Branch                                      | Notes                  |
|---------------|---------|------------|---------------|---------------------------------------------|------------------------|
| add-export    | PASS    | 2          | 8             | fleet/20260520-…/add-export                 | ready to merge         |
| update-billing| PASS    | 3          | 5             | fleet/20260520-…/update-billing             | ready to merge         |
| infra-bump    | BLOCKED | 5 (cap)    | 2             | fleet/20260520-…/infra-bump                 | EF Core 9 migration breaks tests — see BLOCKED.md |

## Merge plan

For each PASS task, suggested merge command:
```bash
git checkout main
git merge --no-ff fleet/20260520-…/add-export
git merge --no-ff fleet/20260520-…/update-billing
```

Note: merging PASS branches in fleet does NOT guarantee they integrate cleanly with each other in main — fleet siblings are isolated. Run any cross-task integration tests after merging.

## Blocked tasks

### infra-bump
<paste of .happysquad/runs/<run-id>/BLOCKED.md from the child's worktree>
```

2. Mark `fleet.json.status: "complete"`.

### Cleanup

After the user merges (or explicitly closes the fleet), prompt:

> "Fleet complete. Remove worktrees? (Branches stay; worktree directories are removed.) — yes / no / keep-failed-only"

- yes → `git worktree remove --force .happysquad/worktrees/<fleet_id>/<slug>` for each task.
- keep-failed-only → remove only PASS task worktrees; keep BLOCKED ones for inspection.
- no → leave everything in place.

Never auto-remove worktrees without asking. The user may want to inspect a BLOCKED run's working state.

## Concurrency limits

`max_parallel` (default 4) controls how many child loops run simultaneously. Higher is faster but consumes more tokens and risks rate limits. The orchestrator should:

- Never exceed `max_parallel`.
- Detect if Claude Agent Team rate-limits a dispatch — if any child fails to start due to capacity, pause new dispatches for 30 seconds and retry.
- Allow override via `/squad-fleet --max=N`.

## Wiki & fleet

Each child can independently offer its post-completion wiki ingest (see squad-loop's wiki-offer section). The fleet orchestrator surfaces a combined offer at the end:

> "Fleet complete. Ingest <K> successful runs into the wiki? — yes (all) / pick / no"

If yes, dispatch `/wiki-ingest --latest-run` for each PASS task (one at a time, sequentially — wiki ingests are NOT parallel-safe because they touch the shared `knowledge/wiki/index.md`).

## Stack profile & fleet

If the project has no `stack-profile.md`, run `/squad-detect` ONCE at the fleet root before spawning children. Children inherit the profile (they share the same project — only worktrees differ, not the project's tech stack).

## What this skill must NOT do

- Do not auto-merge children's branches into main. The user owns merge timing.
- Do not delete worktrees without asking.
- Do not exceed `max_parallel` even when faster-looking.
- Do not run cross-task assumption checks — fleet siblings are by definition independent. If they share assumptions, they should be in-task parallel workstreams of a single loop, not fleet siblings.
- Do not let one BLOCKED child stall the fleet. Other children keep running.

## Token discipline

- Each child's full state stays in the child's worktree. The fleet only needs summaries.
- `fleet.json` is the audit trail; don't duplicate run artifacts.
- The parent agent that orchestrates the fleet reads each child's state.json once at completion — not continuously.

## Resuming an interrupted fleet

If `fleet.json` exists with `status: "in_progress"`:

1. Ask the user: "Fleet `<fleet_id>` is in progress (P completed, Q running, R pending). Resume / Abort / Status-only?"
2. On Resume: dispatch the next pending children to fill up to `max_parallel`. Children that were in progress will have their own `.happysquad/state.json` inside the worktree — they resume from there.
3. On Abort: mark `fleet.json.status: "aborted"`, leave worktrees in place, generate a partial aggregate report.
