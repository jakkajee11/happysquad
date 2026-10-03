---
description: Review the current diff (vs the merge-base with main, or --base <ref>) with the full review stage — test gate, risk-routed specialists, chief reviewer — without running the architect/implementer/tester. Reports findings; routes nowhere.
argument-hint: [--base <ref>] [--headless] [one-line focus for the reviewer]
---

`HS="${CLAUDE_PLUGIN_ROOT}/bin/hs"`. Load `${CLAUDE_PLUGIN_ROOT}/skills/squad-loop/SKILL.md` for the action protocol.

1. Parse `$ARGUMENTS`: `--base <ref>` and `--headless` are flags; anything else is the one-line
   `--task` focus for the reviewer (optional).
2. `--headless` → run `$HS run review-only [--base <ref>] [--task "<focus>"] --driver headless` with
   the Bash tool (`timeout: 600000`); it drives the specialists and the chief itself, in place (no
   worktree — the diff under review is the working tree). Otherwise run
   `$HS run review-only [--base <ref>] [--task "<focus>"]` and follow the skill's action loop
   (`dispatch` / `dispatch_many` / `wait` / `advance`) exactly as for a normal run.
3. On `done`, report: `verdict` (PASS/FAIL), `blockers` and `majors` counts, the `report` path
   (`review.md`), and when there are blockers the `feedback` path. Do not offer a wiki ingest and
   do not suggest a commit — nothing was built.

Notes: the test gate runs the configured suite and coverage over the diff first; a red suite shows
up as a `G-TESTS` blocker, not as a re-dispatch. `nothing to review` means the diff vs the base is
empty. The run is recorded under `.happysquad/runs/<ts>-review-…` and is always COMPLETE
(`verdict` carries the answer).
