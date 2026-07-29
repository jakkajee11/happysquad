---
description: Run only the implementer agent against the current run's design document. Does not auto-advance to testing.
argument-hint: [optional override notes for the implementer]
---

Load the `squad-loop` skill at `${CLAUDE_PLUGIN_ROOT}/skills/squad-loop/SKILL.md` and execute only the IMPLEMENT state.

Steps:

1. Read `.happysquad/state.json` to find the active run-id.
2. If no state exists, or no `design.md` exists for that run, tell the user to run `/squad-architect` (or `/happysquad-loop`) first. Do not proceed.
3. If `$ARGUMENTS` is non-empty, write it to `.happysquad/runs/<run-id>/feedback.md` so the implementer treats this as a fix pass.
4. Update state.json to `current_state = IMPLEMENT`.
5. Launch the `implementer` subagent via the Agent tool with model from config (default `sonnet`). Pass run-id and feedback path if any.
6. Wait for the `IMPLEMENTATION_READY: <path>` marker.
7. Report files changed (`git diff --name-only`) and the path to `implementation.md`. Do not auto-advance to /squad-test.
