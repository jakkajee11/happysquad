---
description: Run several independent tasks in parallel — one headless hs run per git worktree, scheduled by bin/hs fleet. Resumes an in-progress fleet when called with no arguments.
argument-hint: <tasks-file | "task 1" "task 2" … | --frontier | --drain> [--max=N] [--lite]
---

Load `${CLAUDE_PLUGIN_ROOT}/skills/fleet-orchestrator/SKILL.md` and follow its protocol with
`HS="${CLAUDE_PLUGIN_ROOT}/bin/hs"`.

- `$ARGUMENTS` empty and `.happysquad/current-fleet` names an in-progress fleet → Resume section.
- `$ARGUMENTS` empty otherwise → AskUserQuestion for the task list (one per line).
- A path that exists → `--tasks-file`. Otherwise split `$ARGUMENTS` into quoted tasks; `--max=N`,
  `--lite`, `--frontier` and `--drain` are flags, not tasks.
- `--frontier` or `--drain` → no task list needed; `$HS fleet start --frontier` (or `--drain`, which
  implies `--frontier`) reads `docs/agents/issue-tracker.md`'s frontier instead. See "Tracker
  frontier / drain" in the skill.

Never merge branches. Never run `hs fleet cleanup` unless the user asks.
