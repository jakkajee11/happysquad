# Changelog

## 1.1.10 — 2026-10-10

### Added
- `hs run start --design <ticket.md>`: when the design is settled before the loop, a ticket's fenced ` ```hs-design ` JSON block (`ac`, `owned`, `test_owned`, optional `untestable` / `needs_human` / `size`) replaces the architect dispatch. The engine validates it with the ARCHITECT schema (plus non-empty `owned`, and `test_owned` whenever an AC needs a test), writes the ticket as `design.md`, and starts at IMPLEMENT; size/lite follow the 1.1.7 rules. A missing or invalid block falls back to the architect with the reasons in `feedback.md` — the run never fails on it. A task text containing the block counts as `--design` (pumpapp passes whole tickets as the task). The architect stays the in-run fallback for ownership gaps, design conflicts, reviewer `route: architecter` and convergence. A `design` event records which path was taken. In 39 real pumpapp runs only 15 tickets listed AC and none carried ownership, so the block is a ticket-template change on the caller's side before this saves an opus dispatch.

## 1.1.9 — 2026-10-10

### Added
- **Mutation proof from the tester.** TEST `out.json` takes `mutations: [{ac, file, find, replace, tests}]` — per mapped AC, the bug a reviewer would try first. The test gate snapshots the change under test, applies each mutant to its own throwaway worktree (`find` must occur exactly once), and runs the named tests there; the live tree is never touched. `killed` is the proof; `survived` is a `G-MUT` blocker routed to the tester; `not-applied` is a `G-MUT-NOT-APPLIED` major; new tests with no mutations at all is a `G-MUT-NONE` major (refactor/docs runs with no new tests get nothing). Most real TEST blockers (26 of 39 chief blockers) were "the reviewer ran a mutation and the suite stayed green" — this moves that check before review. Results reach the reviewer in `gates_summary` (`mutants=[AC-1:killed, …]`).
- **`needs_human` AC.** ARCHITECT `out.json` takes `needs_human: [{ac, reason, how}]` for an AC only a person can confirm (real-device render, a Builder-run harness). It is still built; the tester need not map it; the reviewer is told not to block on missing rendered/device evidence for it; the run COMPLETEs and `done` carries `needs_human` plus `human_check` → `HUMAN-CHECK.md`, a checklist with how to verify each. A caller must not ship until a person ticks it. Two real runs blocked `cause=permission` waiting on exactly this kind of evidence.

### Fixed
- Headless per-dispatch cost (1.1.8) was empty in real runs: the driver consumed an `out.json` as soon as it landed, while the agent was still finishing its turn — before `claude -p` printed the result line that carries `total_cost_usd`. The driver now consumes only after that agent has exited (still bounded by `agent_timeout`).
- Prompt templates: `needs_human` guidance renders as an optional `{{needs_human_note}}` line, dropped when unset.

## 1.1.8 — 2026-10-10

Unattended-run pass, from 60 real runs (all on the agent-tool driver; 13 checkpoints, 1 run stalled 60 min in ARCHITECT).

### Fixed
- A fresh session resuming a late-iteration run is no longer told to hand off before it does anything. The checkpoint's iteration term (`iteration ≥ checkpoint.iterations`) is run-wide, so every new session on an iteration-3 run got `checkpoint` straight back — 7 of 13 real checkpoints fired with `dispatches: 0`, each costing a human a pointless new session. The iteration term now needs at least one dispatch in this session; the dispatch term is unchanged.

### Added
- `headless.agent_timeout`: minutes per headless agent, by agent name (architecter / reviewer 120, tester / specialist 60, implementer 30, default 60 — each above the p95 of the 60 real runs). An agent past its deadline is killed (whole process group), logged as `agent.timeout`, and retried once through the existing no-output path; a second timeout blocks `cause=agent` with "timed out twice (… min)" in `BLOCKED.md`. Before, only `budget_per_phase` bounded a headless agent, so one that kept reading without spending (the real 60-minute stall) hung the run.
- Per-dispatch cost in `events.jsonl`: each `consume` event carries `cost_usd`, `turns`, `secs` and `model` from the headless log's result line, and the `done` action carries the run's total `cost_usd` (failed validations included). The agent-tool driver has no such log and records nothing, as before.

## 1.1.7 — 2026-10-10

Architect pass, from 39 real runs (every design one workstream; S 19 / M 20; `design.md` median 1,833 words for a median of 4 owned files).

### Fixed
- The architecter can run `hs validate`. Its prompt told it to, but its tools were `Read, Grep, Glob, Write`, so a malformed `out.json` was only caught at `advance` and cost a whole opus re-dispatch. It now has `Bash`, scoped in prose to the validate command.
- An optional `out.json` key set to `null` counts as absent instead of failing validation. Seen live: an implementer wrote `"build_cmds": null, "unmet_ac": null` and was re-dispatched for it. A wrong-typed value is still rejected.

### Changed
- A small design takes the lite path whatever its label: one workstream owning ≤3 literal paths (no globs) is small even when labelled M (two real runs labelled 2-file designs M). A `size` event records the relabel.
- The lite path no longer skips risk routing. It still means one workstream, no CONFLICT and `lite.cap`; RISK now runs, so a small diff touching auth or a migration still gets its specialist.
- `hs validate` (and the engine's own check) caps `design.md` by size: S 600 words, M 1,500, L 3,000. Every later phase reads it on every dispatch. The architect prompt says so and asks for what the implementer can't infer from the repo.
- `assumptions` and `shared_read_only` are retired from the ARCHITECT schema; nothing read them. Assumptions go in `design.md`. An older `out.json` that still carries them is accepted (the keys are dropped before validation).
- `agents/hs-architecter.md` drops the workstream rules that `prompts/architect.md` already carries. The prompt now says a task too big for one design should be split into separate tasks before it reaches the architect.

## 1.1.6 — 2026-10-10

### Fixed
- Single-mode runs now enforce the tester's ownership mechanically. Parallel runs had the CONFLICT ownership gate; single mode skips CONFLICT, so "never touch production code" was prompt text plus the reviewer's read. The engine now snapshots the working tree when it dispatches a single-mode TEST (`pre_tree` on the pending entry) and, when the tester finishes, diffs that tree against the working tree: any changed file outside the workstream's `test_owned` (or `generated`) is an ownership gap routed to the architecter, same as an implementer gap — it decides whether the file is test support (add it to `test_owned`) or production code (the implementer's). The implementer already had its own single-mode check, via its declared `files`.

## 1.1.5 — 2026-10-10

### Changed
- Default perf risk patterns no longer fire on plain queries or HTTP calls. `perf.diff` dropped `SELECT`/`INSERT`/`UPDATE`/`DELETE`/`JOIN`, `.where(`, `.findMany(`, `.toListAsync(`, `.Include(`, `fetch(`, `axios.`, `httpClient.` and `requests.*(`; it keeps `redis`/`memcache`/`memo`, and `perf.paths` (migration, queue, worker, job, scheduler, cache …) is unchanged. Across 29 real runs the old diff patterns triggered 16 perf-specialist dispatches (opus) with 0 blockers and 1 major, mostly on `.where(`; replayed against the new defaults, 18 perf-triggered runs drop to 0. The chief reviewer still covers PERF on every diff. A project `.happysquad/risk-patterns.json` that sets `perf.diff` keeps its own list.

## 1.1.4 — 2026-10-09

### Fixed
- `G-COV-UNVERIFIED` no longer fires for files that have nothing to cover. The coverage gate skips docs/data/assets (`gates.NOT_CODE`: `.md`, `.json`, `.yaml`, images, …), files the change deleted, and (delta rule) files whose diff only removes lines. Found reviewing smarthome S32 with `review-only`: the ticket's `issues/*.md` edits made every such commit carry a "coverage unverifiable" major. A code file with no per-line data is still unverified.

## 1.1.3 — 2026-10-09

### Fixed
- `hs run review-only` got a `G-RED-NONE` major on every run: its synthetic TEST phase declared `new_tests: []` even when the diff added tests. Test files the diff adds (absent at base) are now its new tests and are proven red at base like a tester's (`redgreen.json` in the TEST phase dir), so the verdict applies the same red-first rule as the dev loop — a new test that passes against the old code is a `G-RED` blocker.
- `--base` is pinned to a sha at start. A symbolic ref (`HEAD~1`) failed `_same_ref` against the redgreen ref and produced a `G-RED` "ref mismatch HEAD~1 != HEAD~1"; an unknown ref is now an error up front.
- review-only `feedback.md` is headed "Review findings (review-only: reported, not routed)" instead of "Feedback for iteration 2 (target: implementer)".
- Prompt templates drop a line holding only an unset `{{*_note}}` variable instead of rendering `(none)`. The review prompt's delta paragraph is now `{{delta_note}}`, so first-round reviews no longer carry delta instructions; the architect's `{{lite_note}}` no longer prints `(none)` on non-lite runs.

## 1.1.2 — 2026-10-09

### Fixed
- `G-TESTS` is judged against the base ref. When the suite fails, the gate runs it once more at `base_ref` in a throwaway worktree (cached as `runs/<id>/baseline-tests.json`) and compares failing-test lines. If every failure at head also fails at base, `tests` is `pre-existing`: a `G-TESTS-PRE` major instead of a blocker, the TEST gate doesn't re-dispatch, and the integration gate doesn't send a parallel run back to the architect. A new failure, a green or unrunnable base, an agent test command failing, a timeout, or output with no recognisable failure lines all keep the blocker; `G-TESTS` now names the new failures. Found on a toy repo whose `sub()` was broken at base: every run, review-only included, failed on a defect the diff never touched.

## 1.1.1 — 2026-10-09

### Fixed
- Review scope: an untracked file that existed before the run (already in the base snapshot) counted as changed. `changed_files` listed every untracked file, so a user's scratch file reached risk routing, coverage, the parallel ownership gate ("unowned") and the reviewer, while the prompt's `git diff <base>` showed it as deleted. `changed_files` now diffs the base against a tree of the working tree, and the review/specialist prompts give that same diff (`git diff <base> <tree>`) plus the file list.
- The chief reviewer and specialists now cap a defect already present at the base, in code the diff neither changes nor newly exercises, at major marked "pre-existing". Before, such a blocker outside the fixer's owned files repeated every round until convergence BLOCKED the run.
- Delta review gets the fix pass's own diff (`git diff <iter_ref> <tree>`) and its file list instead of only the whole-run diff, so "scan the touched files" has a concrete target.
- `--fail-on-empty-test-suite` is in the default `allowed_flags`. The chief reviewer writes phpunit verifies as `phpunit --fail-on-empty-test-suite --filter X` (so a filter matching nothing fails instead of passing green), and `provenance.classify` rejected the unknown flag: every such verify read `untrusted`, a fixed blocker never cleared, and the loop re-routed to the implementer until the iteration cap. Found on ev-management ticket 51. A project `allowed_flags` still replaces the list whole.
- `hs redgreen` on PHP/Composer repos read every test as `green`. `vendor/` was symlinked into the old-ref worktree, and Composer's autoloader derives the project root from `dirname(vendor/)` via `__DIR__`, which PHP resolves through the symlink to the live tree — so `App\` loaded the changed code and the old ref never ran. `vendor/` is now copied (`shutil.copytree(symlinks=True)`, ~2 s for 62 MB); `node_modules`, `.venv` and `.env.testing` are still linked. Found on ev-management ticket 47, where the tester had to work around it with `--link`/`--cmd`.

## 1.1.0 — 2026-10-03

### Added
- `/squad-review` is back: `hs run review-only [--base <ref>] [--task …] [--driver headless]` reviews the diff vs the merge-base with main (or `--base`) with the full review stage — test gate and coverage over the diff, risk-routed specialists, chief reviewer — without running the architect/implementer/tester. A FAIL ends the run with `verdict: FAIL` and `feedback.md`; it never routes.

- `hs wiki lint [--dry-run]`: the deterministic half of the wiki lint (index consistency, broken internal links fixed by unique basename, raw references, See Also pruning, log entry) in python; `/wiki-lint` runs it first and leaves only the judgement pass to the LLM.
- Tracker frontier: `hs frontier` reads the Matt Pocock issue tracker (`docs/agents/issue-tracker.md`: local `.scratch/*/issues/*.md`, GitHub via `gh`, GitLab via `glab`) and returns the ready-for-agent tickets whose blockers are done and that are not `squad:passed`. `hs fleet start --frontier` runs that snapshot as a fleet; `--drain` runs it serially (max 1) and pumps newly-unblocked tickets in as children finish; a completed ticket is labelled `squad:passed` (never closed). Empty frontier → `status: empty`, no fleet dir — safe under `/loop 5m /squad-fleet --drain`.
- Context checkpoint (spec §8.9, agent-tool driver only): after `checkpoint.iterations` (3) or `checkpoint.dispatches` (12) in one Claude session, `hs` returns a `checkpoint` action between phases — writes `HANDOFF.md` and tells the orchestrator to hand off to a fresh session with `/squad-resume`. Once per session; never for headless runs; `checkpoint.enabled: false` turns it off.
- `escalation.model` (spec §8.6): when convergence would first take a repeated blocker away from the agent that failed it (repeat / zero-progress → architecter), spend one borrowed round on that model for the implementer/tester instead; once per run, then convergence resumes. Default off.

### Deferred to 1.2
- `hs brainstorm` (moving the 3-round brainstorm orchestration into the engine). The 0.16-style skill-driven brainstorm still works end to end — it ran this project's own spec review (5+5+1+4 dispatches, zero marker failures) — so there is no measured defect to fix; the gain would be code-owned resume/markers only. Revisit when a brainstorm actually stalls.

### Changed
- `interactive` is no longer a config key (accepted silently from old configs). The engine never asks a question; every prompt 0.16 used to raise was either moved into the skills or removed (spec Q8).

## 1.0.0 — 2026-10-03

### Added
- `hs fleet start|advance|wait|status|cleanup` (spec §12): N independent tasks as headless runs, one git worktree each under `<repo>-hs-wt/fleet-<id>/<slug>` on branch `fleet/<id>/<slug>`, scheduled up to `max_parallel`; a child whose driver dies is re-dispatched once via `hs resume`, then marked stalled; aggregate report with merge commands; nothing is ever merged. `/squad-fleet` and the fleet skill (~350 words) relay it.
- `evals/test_fleet.py`: 6 fake-driver tests (isolation, max_parallel, BLOCKED sibling, idempotent advance, cleanup, tasks file).

### Changed
- `/brainstorm` dispatches the v1 `hs-*` agents for the four engineering roles (`product` unchanged).

### Fixed
- Brainstorm rounds dispatched to the `hs-*` agents could stall on the role files' dev-loop procedure (owned files, red→green, `out.json`/validate); every `prompts/brainstorm/*.md` now opens with a waiver.

### Removed
- The four 0.16 dev-loop agent files (`agents/{architecter,implementer,tester,reviewer}.md`), the two 0.16 specialist files (`security-reviewer.md`, `performance-reviewer.md`, replaced by `hs-specialist.md` + `references/axis-*.md`), and the 0.16 fleet orchestrator prose. All kept in `happysquad-ext`. The 0.16 chief reviewer is kept in `happysquad-ext` and at tag `v0.16.2` for the recall baseline.

### Still 1.1
- `/squad-review` review-only, `ask`/non-interactive defaults (`interactive` is a no-op), `hs brainstorm`, `hs wiki lint`, tracker frontier/drain, context checkpoint, `escalation.model`.

## 1.0.0-rc1 — 2026-10-03

The engine rewrite (spec: `docs/spec/v1-rewrite.md`). Every deterministic part of the dev loop moved out of LLM prose into a python3 stdlib engine, `bin/hs`.

### Added
- `bin/hs` + `hs/` package: state machine, `out.json` contracts per phase, evidence gates (build, test, coverage with a delta rule, red→green proof in a throwaway worktree), ownership + integration conflict gate, risk-routed specialist reviewers, verdict truth table, inner fix loop with per-finding `verify` and delta review, convergence by `prior_id`/fingerprint, lite path for size-S tasks, crash-safe `events.jsonl`, `hs resume`.
- Headless driver: `hs run start --driver headless` drives `claude -p` itself in an isolated worktree on `hs/<run-id>` (`--headless` on `/happysquad-loop`). ≈ 7× cheaper per completed task than 0.16.2 on the bench.
- `agents/hs-*.md`: five trimmed agent files (judgement rules only; the rendered dispatch prompt carries the contract). `prompts/` dispatch templates, `prompts/brainstorm/` round instructions, `references/` risk patterns and axis checklists.
- Evals: 130+ model-free tests (`evals/test_*.py`), 18 fake-driver scenarios, `evals/smoke.sh`, bench harness (`evals/bench/`) with the 0.16.2 baseline and the v1.0 results, seeded-bug recall fixture.

### Changed
- `/happysquad-loop`, `/squad-architect`, `/squad-status`, `/squad-resume` drive the engine; the orchestrator skill is ~400 words and reads no artefacts.
- Hooks run through `hs hook`; the Stop progress nudge is opt-in (`hooks.stop_progress_nudge`), and both hooks are silent for headless children.
- `hs init` seeds `build_cmd` / `test_cmd` / `coverage_report` from manifests and writes a `.happysquad/.gitignore` that keeps `config.json` committable.
- Coverage is gated on lines the change added (`coverage_rule: delta`), not whole-file percent.

### Removed (moved to the `happysquad-ext` plugin)
- External executors (glm/opencode) and the tmux pane rule, `/squad-assemble` + team assembly, `/ask-kilo`, requirement/standard specialist reviewers, `/squad-implement`, `/squad-test`, `/squad-drain`, worktree-per-workstream fallback, Fable-specific escalation.

### Known gaps (1.1)
- `/squad-review` (review-only run), `hs fleet` (P4; the 0.16 `/squad-fleet` remains and is unsupported on the new engine), `hs brainstorm`, `hs wiki lint`, tracker frontier/drain, context checkpoint, `escalation.model`.

## 0.16.2 and earlier

See git history. 0.16.x was the last prose-orchestrated release.
