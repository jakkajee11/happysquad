---
description: Run only the tester agent against the current run's implementation. Writes tests, runs them, reports coverage. Does not auto-advance to review.
argument-hint: [optional notes about extra test focus]
---

Load the `squad-loop` skill at `${CLAUDE_PLUGIN_ROOT}/skills/squad-loop/SKILL.md` and execute only the TEST state.

Steps:

1. Read `.happysquad/state.json` to find the active run-id.
2. If no state exists, or `implementation.md` is missing for that run, tell the user to run `/squad-implement` first. Do not proceed.
3. If `$ARGUMENTS` is non-empty, append it to `.happysquad/runs/<run-id>/feedback.md` so the tester knows what to emphasize.
4. Update state.json to `current_state = TEST`.
5. Launch the `tester` subagent via the Agent tool with model from config (default `sonnet`).
6. Wait for the `TESTS_READY: <path> status=<all-pass|some-fail> coverage=<percent>` marker.
7. Report pass/fail, coverage percent, and the test-report.md path. Do not auto-advance to /squad-review.
