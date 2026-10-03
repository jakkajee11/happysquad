---
name: fleet-orchestrator
description: |
  Runs several independent happysquad tasks at once, each as a headless hs run in its own git
  worktree and branch, scheduled by `bin/hs fleet` up to max_parallel. Trigger on /squad-fleet,
  "run these in parallel", "process this backlog", "fan out across worktrees".
---

# Fleet

`hs fleet` owns the fleet: it creates one worktree per task, starts each task as a headless run
(`hs run start --driver headless --no-isolate` inside that worktree), re-dispatches a child whose
driver died once, and writes the aggregate report. You relay `hs fleet` commands and report.

```
HS="${CLAUDE_PLUGIN_ROOT}/bin/hs"
```

## Protocol

1. **Tasks.** From `$ARGUMENTS`: a file path → `--tasks-file <path>` (one task per line, `-`/`*`
   bullets and `#` comments allowed); otherwise each quoted argument is a task. Nothing resolvable →
   AskUserQuestion for the list. `--max=N` → `--max N`. `--lite` passes through.
2. **First run in a project:** if `.happysquad/config.json` is missing, `$HS init` and show what it
   seeded; `test_cmd` null → stop and ask for it. If `.happysquad/stack-profile.md` is missing, run
   `/squad-detect` once.
3. **Start.** `$HS fleet start <tasks…> [--max N] [--lite]`. Parse the JSON line: `fleet_id`,
   `counts`, `children[]` (slug, status, branch, worktree).
4. **Wait.** `$HS fleet wait --timeout 540` with the Bash tool (`timeout: 600000`). It prints the
   fleet summary when the fleet is `complete`, or the same summary with `timed_out: true` — then
   run it again. Never poll with your own loop; never end the turn while `status` is `in_progress`.
5. **Report** (≤ 200 words): fleet_id, counts, per-child line (slug · verdict · iterations ·
   branch), the `merge` commands verbatim, the `report` path, and for each BLOCKED child the
   `BLOCKED.md` path from the report. Never merge anything.
6. **Cleanup** only when the user asks: `$HS fleet cleanup` removes COMPLETE worktrees (branches
   stay); `--all` also removes BLOCKED/stalled ones.

## Resume

`/squad-fleet` with no arguments while `.happysquad/current-fleet` names an `in_progress` fleet →
`$HS fleet wait` continues it (children already finished are recorded, dead drivers are
re-dispatched once, pending ones are launched). `$HS fleet status` shows the picture without
waiting.

## Rules

- One `hs fleet` command per step; read every fact from its JSON.
- Do not open child worktrees, read their state, or run their builds yourself.
- Siblings are isolated by construction: PASS branches are not proven to integrate with each other;
  say so when you print the merge commands.

## Tracker frontier / drain

`$HS fleet start --frontier` reads `docs/agents/issue-tracker.md` (Matt Pocock `/to-tickets` layout)
and dispatches its **frontier** — open `ready-for-agent` tickets whose blockers are all done — instead
of `<tasks>`. `--drain` implies `--frontier`, runs serially (`max_parallel` defaults to 1, override with
`--max`), and pumps: as each child finishes, it re-reads the frontier and appends any ticket that just
unblocked. A completed ticket is labelled `squad:passed` (never closed — the user owns close/merge
timing) and excluded from every future frontier read. Empty frontier → `$HS fleet start --drain` prints
one line, "Frontier empty — nothing to drain." and stops with success — safe under
`/loop 5m /squad-fleet --drain`. `$HS frontier` prints the frontier JSON without starting a fleet.
