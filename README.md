# happysquad

A software-development squad for Claude Code: an architecter, implementer, tester, and reviewer hand work off through files until the reviewer's findings clear or the round cap is hit. **The LLM does only the work that needs judgment — design, code, tests, review. A python3 engine (`bin/hs`) owns every state transition, gate, and verdict.**

That split is the whole point of the 1.0 rewrite. 0.16 had an LLM orchestrator reading 7,000 words of prose and hand-rolling state updates, gate re-runs, and convergence checks every iteration — mistakes were routine and none of it was testable. v1.0 moves all of that into tested code and leaves the model nothing to get wrong.

## Quick start

Install as a Claude Code plugin (point `--plugin-dir`, or your marketplace, at this repo).

```
hs init
```

Creates `.happysquad/`, a `.gitignore` that keeps `config.json` committable, and seeds `config.json` with `build_cmd` / `test_cmd` / `coverage_report` guessed from your manifest (`package.json` scripts, `pyproject.toml`/pytest, `go.mod`, `Cargo.toml`, `*.csproj`). `test_cmd` is the one required key — a run won't start without it.

```json
// .happysquad/config.json — minimum to run
{"build_cmd": "pnpm build", "test_cmd": "pnpm test -- --coverage", "coverage_report": "coverage/lcov.info"}
```

Everything else (cap, models, coverage threshold, …) falls back to the defaults in [Config reference](#config-reference).

```
/happysquad-loop <task>
/happysquad-loop <task> --headless
/squad-status
/squad-resume
```

- `/happysquad-loop <task>` drives the engine from inside your session: an orchestrator LLM relays each `hs` action through the Agent tool and reports back.
- `/happysquad-loop <task> --headless` has `hs` drive `claude -p` itself, in an isolated git worktree on branch `hs/<run-id>`. No orchestrator LLM turns are spent. On completion the run reports `worktree`, `branch`, and a `suggested_merge` (`git merge --no-ff hs/<run-id>`) — nothing is auto-merged.
- `/squad-status` → `hs status`: current run, state, iteration/cap, workstreams, pending dispatches.
- `/squad-resume` → `hs resume`: picks up a run that stopped mid-phase (crash, closed session, killed agent) from whatever's already on disk.

## How a run works

```
ARCHITECT ─▶ IMPLEMENT(waves) ─▶ TEST(waves) ─▶ CONFLICT ─▶ RISK ─▶ SPECIALISTS ─▶ REVIEW ─┬─▶ COMPLETE
   ▲                                                                                        │
   │◀── route=architecter / CONFLICT fail / ownership_gap / design_conflict ◀───────────────┤
   │                                                                                        │
   │      ┌── every blocker machine-verifiable ──▶ INNER_FIX ─▶ verify ─▶ gates ─▶ REVIEW(delta)
   │      │
   └ FAIL ┴── any manual/untrusted blocker ─▶ IMPLEMENT/TEST (subset) ─▶ … ─▶ REVIEW
```

Every agent writes an `out.json` (the phase's machine-checked contract) plus an artefact — `design.md`, `implementation.md`, `test-report.md`, `review.md` (+ `sec.md`/`perf.md` from specialists). No completion markers; the agent runs `hs validate <out.json>` itself before finishing.

Between phases, `hs` (not the LLM) checks:

- **Gate build** — `config.build_cmd` plus any agent-added commands that pass the provenance rules (full-prefix match against a config command, no shell metacharacters).
- **Gate test** — `config.test_cmd`, coverage from the report (lcov / cobertura / istanbul / pytest-cov), and **red→green proof**: every new test is re-run in a throwaway worktree against the pre-fix ref and must have failed there first.
- **Conflict gate** (parallel runs only) — every changed file belongs to exactly one workstream's ownership.
- **Risk → specialists** — a regex pass over the diff (`references/risk-patterns.json`) decides whether `security`/`performance` specialists get dispatched alongside the chief reviewer.
- **Verdict** — `hs` computes PASS/FAIL from a truth table over tests / coverage / redgreen / specialist findings / reviewer findings. The reviewer never emits a verdict, only findings with a `verify` command each.

A FAIL where every blocker has a `verify` command takes the **inner fix loop** instead of a full round: fix → re-verify → gates → a delta review of just the fix (capped at `inner_cap` passes). **Convergence**: a blocker seen twice routes normally, a third time forces the architecter, and a repeat after that (or two rounds that fixed nothing) stops the run `BLOCKED cause=convergence`. A `size: S` design auto-enters the **lite path** — one workstream, no CONFLICT/RISK/SPECIALISTS, `review_mode=single` — unless `--full` is passed.

`BLOCKED` causes the engine produces today: `validation` (out.json kept failing schema), `gate` (build/test kept failing), `convergence` (cap hit or a recurring blocker), `agent` (a headless `claude -p` dispatch errored twice with no output). Each writes `BLOCKED.md` with the iteration history and what was tried. (`test_cmd` missing is checked before a run even starts — it's reported as a plain error, not a BLOCKED run.)

## Drivers

| | agent-tool (default) | headless |
|---|---|---|
| who spends LLM turns | orchestrator session + the agents | only the agents — `hs` runs the loop itself |
| invoked by | `/happysquad-loop` in a session | `/happysquad-loop <task> --headless`, or `hs run start --driver headless` |
| isolation | your working tree | isolated worktree + branch (`headless.isolate: "worktree"`, default) |
| best for | interactive work, a first run in a new repo | overnight/unattended, CI, fleet children |

Measured on this repo's own bench (`evals/bench/tasks.md`, 5 small tasks): 0.16.2 ≈ **$5.6/COMPLETE** (one harness-forced manual resume), hs headless ≈ **$0.66/COMPLETE**, hs agent-tool ≈ **$3.8/COMPLETE** — the orchestrator session itself costs about $3.2 on top of the ~$0.6 of agent work. Seeded-bug reviewer recall was 3/3 for both 0.16.2 and hs. Headless is the default for unattended work; agent-tool is where you'd watch each step.

The headless worktree lives outside `.git/` (Claude Code refuses writes under any `.git/` path) — default a sibling directory `<repo>-hs-wt/<run-id>`, overridable with `headless.worktree_dir`. Pass `--no-isolate` (or set `headless.isolate: "none"`) to run in place instead.

## Agents

| agent | model | tools | job |
|---|---|---|---|
| `hs-architecter` | opus | Read, Grep, Glob, Write | design + numbered AC + workstream/ownership breakdown |
| `hs-implementer` | sonnet | Read, Write, Edit, Grep, Glob, Bash | production code only, inside its owned files |
| `hs-tester` | sonnet | Read, Write, Edit, Grep, Glob, Bash | tests + red→green proof; never touches production code |
| `hs-reviewer` | opus | Read, Grep, Glob, Bash, Write | reads the diff itself, files findings + a `verify` each, never a verdict |
| `hs-specialist` | opus | Read, Grep, Glob, Bash, Write | one axis (security or performance) against its checklist file |

Review axes: `REQ` / `SEC` / `PERF` / `STD` / `SIMPL` / `TEST`. **`SIMPL` never blocks** — a `blocker` finding tagged `SIMPL` is downgraded to `major` before the verdict is computed. `hs` computes the PASS/FAIL verdict and the route; the reviewer's job ends at filing findings.

(`product`, opus, also exists for brainstorm sessions only — it never runs inside `/happysquad-loop`.)

## Config reference

All keys live in `hs/config.py` `DEFAULTS`; `.happysquad/config.json` overrides by key (nested dicts merge one level deep, unknown keys warn once). `hs config` prints the effective config.

| key | default | |
|---|---|---|
| `driver` | `"agent-tool"` | `agent-tool` \| `headless` \| `fake` |
| `cap` | 5 | iterations before `BLOCKED cause=convergence` |
| `inner_cap` | 2 | delta-review passes inside the inner fix loop before falling back to a full round |
| `gate_retries` | 1 | re-dispatches on a gate failure before `BLOCKED cause=gate` |
| `validation_retries` | 2 | re-dispatches on a schema-invalid `out.json` before `BLOCKED cause=validation` |
| `gate_timeout` | 600 | seconds per gate subprocess |
| `coverage_threshold` | 80 | minimum coverage, inclusive; `null` skips the coverage term |
| `coverage_rule` | `"delta"` | `delta` = gate only lines the diff added; `file` = whole-file percent |
| `review_mode` | `"split-on-risk"` | when specialists are dispatched alongside the chief reviewer |
| `max_parallel` | 4 | concurrent workstream dispatches / headless subprocesses |
| `models.*` | architecter/reviewer/specialist/product = opus, implementer/tester = sonnet | per-agent model override |
| `lite.auto` / `lite.cap` | `true` / 3 | size-S designs auto-enter the lite path; its own iteration cap |
| `build_cmd` / `test_cmd` / `coverage_report` | `null` | seeded by `hs init`; `test_cmd` is required to start a run |
| `redgreen_cmd` | `null` | template with `{file}`; default `"<test_cmd> {file}"` |
| `allowed_flags` | `--run`, `--filter`, `--grep`, `-t`, `-k`, `--testNamePattern`, `--coverage` | flags an agent-supplied command may add past a config-command prefix |
| `generated` | lockfiles, `**/__snapshots__/**` | exempt from the ownership/conflict check |
| `headless.budget_per_phase` | 2.0 | `--max-budget-usd` per `claude -p` dispatch |
| `headless.allowed_tools` / `disallowed_tools` | `Read,Write,Edit,Grep,Glob,Bash` / git push/reset/clean/checkout/commit, `rm -rf`, curl, wget, sudo, gh | passed to `claude -p`; the deny-list is a reinforcing layer, not a wall |
| `headless.isolate` | `"worktree"` | `worktree` (default) or `none` |
| `headless.worktree_dir` | `null` | override; default sibling dir, never under `.git/` |
| `headless.poll_interval` | 3 | seconds between driver polls |
| `hooks.stop_progress_nudge` | `false` | Stop-hook progress nudge, opt-in |
| `wiki.offer` | `true` | offer a wiki ingest on COMPLETE |
| `fleet.base_branch` | `null` | base branch for `hs fleet start` (not shipped yet — see below) |

## Layout

```
.happysquad/
├── .gitignore                                 # hs init writes this
├── config.json                                # committed
├── stack-profile.{md,json}, risk-patterns.json  # committed (optional)
├── current                                    # active run-id, one line
└── runs/<run-id>/
    ├── state.json  .lock  events.jsonl
    ├── task.md  design.md
    ├── prompts/<PHASE>-i<N>[-<ws>].md
    ├── <PHASE>-i<N>[-<ws>]/out.json + artefact + logs/
    ├── gates-<PHASE>-i<N>[-<ws>].json
    └── conflict.json  risk.json  feedback.md  BLOCKED.md
```

`runs/`, `current`, `fleets/`, `worktrees/`, `brainstorms/` are all gitignored by the `.gitignore` `hs init` writes (`/*` plus re-includes) — per-run state is throwaway working data, not something to commit or diff. Only `config.json`, `.gitignore`, and the optional stack/risk files are tracked.

## Brainstorm, fleet, stack detector, wiki

Unchanged from 0.16 except where noted:

- **Brainstorm** (`/brainstorm`) — same 3-round orchestration (product/architecter/implementer/tester/reviewer diverge → cross-review → converge). Only the per-round prompt text moved, to `prompts/brainstorm/*.md`. An engine-driven `hs brainstorm` is planned for 1.1.
- **Fleet** (`/squad-fleet`) — still the 0.16 implementation: one git worktree per task, run concurrently. It drives the 0.16 loop, not `hs` — **unsupported on the new engine** until `hs fleet` (P4) ships in 1.1.
- **Stack detector** (`/squad-detect`) — same scan; now also feeds `hs init`'s `build_cmd`/`test_cmd`/`coverage_report` seeding.
- **Wiki** (`/wiki-ingest`, `/wiki-ask`, `/wiki-lint`) — unchanged.

## Evals & bench

```
python3 -m unittest discover -s evals -p 'test_*.py'
```

Model-free unit/e2e tests: schema validation, coverage parsers, redgreen classification, command provenance, the verdict truth table, convergence, concurrency/locking, headless argv construction, and fake-driver scenarios run through `evals/fake_agent.py` / `evals/fake_claude.py`. No model calls.

- `evals/smoke.sh` — one real `claude -p` headless loop on a toy repo, budget-capped, asserts COMPLETE.
- `evals/bench/run.sh <B1..B5> <0.16|hs>` — runs one bench task through one engine in a throwaway worktree; an oracle re-runs the test command after COMPLETE.
- `evals/bench/recall.sh <0.16|hs>` — hands a reviewer a diff with 3 seeded bugs and scores how many it catches.

Headline numbers (`evals/bench/tasks.md`, P2 dogfood gate, 5 tasks on this repo's own `hs/`):

| | 0.16.2 | hs headless | hs agent-tool |
|---|---|---|---|
| COMPLETE | 4/5 (1 harness-forced resume) | 5/5 | 5/5 (B5 only) |
| $ / COMPLETE | ≈ 5.6 | ≈ 0.66 | ≈ 3.8 |
| seeded-bug recall | 3/3 | 3/3 | — |

## Migrating from 0.16

- **State**: one shared `.happysquad/state.json` → per-run `.happysquad/runs/<run-id>/state.json`; `.happysquad/current` points at the active run. Old 0.16 runs don't carry over.
- **Hand-off**: completion markers (`DESIGN_READY: …`, etc.) are gone — every agent writes `out.json` and runs `hs validate` before finishing.
- **Coverage**: gated on lines the diff *added* (`coverage_rule: "delta"`) by default, not whole-file percent — 0.16 never actually enforced per-file coverage on touched files, so this is a real behavior change, not a rename.
- **Removed, moved to the `happysquad-ext` plugin** (not yet published): `/squad-assemble` + team assembly, `/ask-kilo`, `/squad-implement`, `/squad-test`, `/squad-drain`, the `requirement-reviewer`/`standard-reviewer` specialists, external executors (glm/opencode) + the tmux pane rule, worktree-per-workstream fallback, Fable-specific escalation.
- **Not removed, but frozen**: `/squad-fleet` stays on the 0.16 loop until `hs fleet` ships (1.1).

## License

MIT
