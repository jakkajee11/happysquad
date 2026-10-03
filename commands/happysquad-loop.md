---
description: Run the full happysquad loop (architect → implement → test → conflict-gate → risk → specialists → review) on a task, iterating until pass or the round cap. Auto-detects parallel workstreams from the architecter's design and dispatches implementer/tester in parallel waves when safe.
argument-hint: <task> [--lite] [--no-parallel] [--headless]
---

`HS="${CLAUDE_PLUGIN_ROOT}/bin/hs"`

Load `${CLAUDE_PLUGIN_ROOT}/skills/squad-loop/SKILL.md`.

If `$ARGUMENTS` is empty (after stripping flags), ask the user for the task with AskUserQuestion. Do
not invent a task. Strip `--lite`, `--no-parallel`, `--headless` to get the task text.

If `--headless` was passed:

1. Run `$HS run start "<task>" --driver headless` (plus `--lite`/`--no-parallel` if passed) with the
   Bash tool, `timeout: 600000`. The engine drives `claude -p` itself inside an isolated worktree —
   do not dispatch any agents yourself.
2. Report the `done` JSON it prints: `status`, `run_id`, `worktree`, `branch`, `suggested_merge`.
   Stop.

Otherwise, follow the skill's protocol for this task, starting with `$HS run start "<task>"
--driver agent-tool` (plus `--lite`/`--no-parallel` if passed).
