# Changelog

## 1.1.0 — in progress

### Added
- `/squad-review` is back: `hs run review-only [--base <ref>] [--task …] [--driver headless]` reviews the diff vs the merge-base with main (or `--base`) with the full review stage — test gate and coverage over the diff, risk-routed specialists, chief reviewer — without running the architect/implementer/tester. A FAIL ends the run with `verdict: FAIL` and `feedback.md`; it never routes.

- `hs wiki lint [--dry-run]`: the deterministic half of the wiki lint (index consistency, broken internal links fixed by unique basename, raw references, See Also pruning, log entry) in python; `/wiki-lint` runs it first and leaves only the judgement pass to the LLM.
- Context checkpoint (spec §8.9, agent-tool driver only): after `checkpoint.iterations` (3) or `checkpoint.dispatches` (12) in one Claude session, `hs` returns a `checkpoint` action between phases — writes `HANDOFF.md` and tells the orchestrator to hand off to a fresh session with `/squad-resume`. Once per session; never for headless runs; `checkpoint.enabled: false` turns it off.
- `escalation.model` (spec §8.6): when convergence would first take a repeated blocker away from the agent that failed it (repeat / zero-progress → architecter), spend one borrowed round on that model for the implementer/tester instead; once per run, then convergence resumes. Default off.

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
