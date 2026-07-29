---
description: Run only the architecter agent — produce a design document for a task and stop. Does not advance to implementation.
argument-hint: <task description>
---

Load the `squad-loop` skill at `${CLAUDE_PLUGIN_ROOT}/skills/squad-loop/SKILL.md` for the file-layout and state-file conventions, but execute only the ARCHITECT state.

Steps:

1. If `$ARGUMENTS` is empty, ask the user for the task with AskUserQuestion.
2. Generate or reuse a run-id; create `.happysquad/runs/<run-id>/`.
3. Update `.happysquad/state.json` to `current_state = ARCHITECT`, `iteration = 1` (or bump if continuing).
4. Launch the `architecter` subagent via the Agent tool, with model from config (default `opus`). Pass the task, the run-id, and the run directory path.
5. Wait for the `DESIGN_READY: <path>` completion marker.
6. Report the path to the design document and stop. Do not auto-advance to /squad-implement.

Use this command when you want to inspect the design before committing to implementation, or when the design needs human review.
