---
description: Run only the reviewer agent against the current run's code and tests. Produces a PASS/FAIL verdict and routes the issue list, but does not auto-loop.
argument-hint: [optional reviewer focus, e.g. "security only"]
---

Load the `squad-loop` skill at `${CLAUDE_PLUGIN_ROOT}/skills/squad-loop/SKILL.md` and execute only the REVIEW state.

Steps:

1. Read `.happysquad/state.json` to find the active run-id.
2. If `test-report.md` is missing for that run, tell the user to run `/test` first. Do not proceed.
3. If `$ARGUMENTS` is non-empty, pass it to the reviewer as additional focus (e.g. "concentrate on SEC issues").
4. Update state.json to `current_state = REVIEW`.
5. Launch the `reviewer` subagent via the Agent tool with model from config (default `opus`).
6. Wait for the `REVIEW_READY: <path> verdict=<PASS|FAIL> next=<...>` marker.
7. Report verdict, next route, count of blocker/major/minor issues, and the review.md path.
8. If verdict is FAIL, ask the user whether to run the suggested next agent — do not auto-advance.
