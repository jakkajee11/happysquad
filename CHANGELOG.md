# Changelog

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
