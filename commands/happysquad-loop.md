---
description: Run the full happysquad loop (architect → implement → test → conflict-gate → risk → specialists → review) on a task, iterating until pass or the round cap. Auto-detects parallel workstreams from the architecter's design and dispatches implementer/tester in parallel waves when safe. A ticket with an hs-design block skips the architect.
argument-hint: <task> [--design <ticket.md>] [--lite] [--no-parallel] [--headless]
---

`HS="${CLAUDE_PLUGIN_ROOT}/bin/hs"`

Load `${CLAUDE_PLUGIN_ROOT}/skills/squad-loop/SKILL.md`.

If `$ARGUMENTS` is empty (after stripping flags), ask the user for the task with AskUserQuestion. Do
not invent a task. Strip `--design <file>`, `--lite`, `--no-parallel`, `--headless` to get the task text.

`--design <ticket.md>`: pass it through to `run start`. When the ticket holds a complete
` ```hs-design ` JSON block (`ac`, `owned`, `test_owned`, optional `untestable` / `needs_human`), the
engine skips the architect and starts at IMPLEMENT; otherwise it runs the architect as usual. A task
text that itself contains the block counts the same.

If `--headless` was passed:

1. Run `$HS run start "<task>" --driver headless` (plus `--design`/`--lite`/`--no-parallel` if passed)
   with the Bash tool, `timeout: 600000`. The engine drives `claude -p` itself inside an isolated
   worktree — do not dispatch any agents yourself.
2. Report the `done` JSON it prints: `status`, `run_id`, `worktree`, `branch`, `suggested_merge`,
   `cost_usd`, and `needs_human` / `human_check` when present. Stop.

Otherwise, follow the skill's protocol for this task, starting with `$HS run start "<task>"
--driver agent-tool` (plus `--design`/`--lite`/`--no-parallel` if passed).
