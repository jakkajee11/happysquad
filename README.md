# happysquad

A five-agent software development squad with five layers, all designed to run safely in Claude Agent Team's parallel-dispatch model:

- A **stack detector** that scans the project once and tells each agent which stack-specific skills to load.
- A **brainstorm session** for analyzing new requirements together before any code is touched.
- An **automated hand-off loop** that auto-parallelizes within a task — architecter partitions the work into workstreams with file-ownership maps, implementer + tester run concurrently per workstream, a conflict-detection gate catches partition violations before review.
- A **fleet mode** that runs multiple independent loops in parallel git worktrees, one task per worktree, all on separate branches.
- A **compounding project wiki** (Karpathy-style) that captures designs, decisions, and lessons across every run so the squad gets smarter over time.

## Agents

**Core agents (always present):**

| Agent         | Model  | Job                                                                                       |
|---------------|--------|-------------------------------------------------------------------------------------------|
| `product`     | opus   | PM voice — customer intent, success metrics, must-have vs nice-to-have, scope boundary.   |
| `architecter` | opus   | Designs components, data model, contracts, AC, and workstream partitioning.               |
| `implementer` | sonnet | Writes the code that satisfies the design. No tests.                                      |
| `tester`      | sonnet | Writes and runs tests. Reports coverage and per-criterion mapping. No production code.    |
| `reviewer`    | opus   | Chief reviewer. In single mode runs all axes; in split modes aggregates specialists.      |

**Specialist reviewers (dispatched conditionally):**

| Agent                  | Model  | Axis | When dispatched                                                  |
|------------------------|--------|------|------------------------------------------------------------------|
| `security-reviewer`    | opus   | SEC  | Always in `split` mode; in `split-on-risk` when diff matches auth/payment/secrets/dependency/migration patterns |
| `performance-reviewer` | opus   | PERF | Always in `split`; in `split-on-risk` when diff adds DB queries, migrations, loops with calls, caching changes |
| `requirement-reviewer` | sonnet | REQ  | Only in `split` mode (REQ is core to every diff; risk-conditional dispatch adds no signal) |
| `standard-reviewer`    | sonnet | STD  | Only in `split` mode                                              |

`product` participates in brainstorms by default; it does not run inside `/happysquad-loop` unless you invoke it explicitly. The other four (core, non-product) plus 0-4 specialists form the dev-loop quartet + reviewer council.

Model assignment uses the **Balanced** strategy — heavier reasoning (product judgment, design, review) on opus; mechanical work (write code, write tests) on sonnet. Override in `.happysquad/config.json`.

## Commands

| Command            | Description                                                                       |
|--------------------|-----------------------------------------------------------------------------------|
| `/brainstorm`      | Run a 3-round session where all five agents analyze a topic together. **Use when the path is unclear.** |
| `/squad-assemble`  | Analyze a spec and recommend team composition (review mode, specialists, models, external-executor roles) behind an approval gate. Optional pre-loop step. |
| `/happysquad-loop`  | Run the full architect → implement → test → review loop until PASS or cap. **Use when the path is clear.** |
| `/squad-architect`       | Run only the architecter — produce a design, stop.                                |
| `/squad-implement`       | Run only the implementer against the current run's design.                        |
| `/squad-test`            | Run only the tester against the current run's implementation.                     |
| `/squad-review`          | Run only the reviewer against the current run's tests.                            |
| `/squad-status`    | Show the active run / brainstorm state, history, and recommended next action.     |
| `/wiki-ingest`     | Ingest a source (happysquad artifact, URL, file, paste) into the project wiki.     |
| `/wiki-ask`        | Ask the wiki a question — answers with citations to wiki articles.                |
| `/wiki-lint`       | Run quality checks on the wiki (auto-fix links + heuristic findings).             |
| `/squad-detect`    | Scan the project to detect tech stack and write per-agent skill recommendations.  |
| `/squad-fleet`     | Run multiple independent happysquad-loop tasks in parallel, each in its own worktree. |
| `/squad-drain`     | Serially drain the tracker frontier — ready-for-agent tickets one at a time, pumping as blockers clear. Pair with `/loop` for a standing watch. |
| `/squad-resume`    | Continue the most recent in-progress run / brainstorm / fleet after a session restart. |

All commands share `.happysquad/` state for runs/brainstorms and `knowledge/` for the wiki, so you can move freely between modes. A typical full workflow is `/brainstorm` → review consensus → ingest decision to wiki → `/happysquad-loop` → ingest design and lessons to wiki.

## Review modes

The reviewer council operates in one of three modes (set in `.happysquad/config.json`):

```json
{ "review_mode": "split-on-risk" }
```

**`single`** — one `reviewer` (opus) personally evaluates all six quality axes (REQ / SEC / PERF / STD / SIMPL / TEST) plus CONFLICT. Cheapest token-wise; sufficient for low-risk CRUD work.

**`split`** — four specialists (`security-reviewer`, `performance-reviewer`, `requirement-reviewer`, `standard-reviewer`) run in parallel; the chief `reviewer` aggregates their verdicts, runs TEST + CONFLICT itself, and makes the final routing decision. Highest cost but strongest audit trail; recommended for financial / healthcare / regulated codebases where SEC issues are expensive to miss.

**`split-on-risk`** (default) — middle ground. The orchestrator runs a risk-detection pass on the diff:
- Files matching auth/payment/secrets/credentials/CORS/CSP/migration patterns OR diffs adding dependencies → dispatch `security-reviewer` in parallel.
- Diffs adding DB queries, migrations, loops-with-calls, caching, queues, workers → dispatch `performance-reviewer` in parallel.
- REQ and STD are always handled by the chief reviewer (REQ is core; STD is mechanical — specialists add little).

The dispatched specialists run **in parallel with the chief reviewer**, not before. The chief reviewer reads their review files when they complete and dedups across axes. This keeps wall-clock time roughly equal to single-mode review while adding specialist depth where it matters.

## Parallel execution — two levels

The squad is designed for Claude Agent Team's parallel dispatch. There are two distinct parallelism layers:

### Within-task parallelism (single `/happysquad-loop`)

The architecter's design document includes a Workstreams table and an Ownership map. Each workstream is a unit of independent build (e.g. backend / frontend / infra), with a `depends_on` field defining a DAG. The orchestrator:

1. Computes waves by topological sort.
2. Dispatches all workstreams in a wave **in a single message with multiple Agent tool calls** (parallel dispatch).
3. Waits for all wave markers before starting the next wave.
4. Runs a **conflict-detection gate** before review — verifies (a) every changed file is in exactly one workstream's ownership, (b) per-workstream diff sets are disjoint, (c) the merged integration build passes.
5. If any check fails → routes back to architecter (the partition is wrong).

Each `implementer` / `tester` agent receives an `owned_files` list and **refuses to edit anything outside it**. If a file is missing from the list, it stops and writes `OWNERSHIP_GAP` — the orchestrator routes back to architecter rather than letting workstreams silently collide.

For genuinely overlapping designs, the orchestrator falls back to git worktrees per workstream (configurable via `parallel_isolation` in `.happysquad/config.json`). Default = ownership-first, worktree-fallback.

### Fleet parallelism (`/squad-fleet`)

For multiple unrelated tasks (a backlog of features, a sweep of bug fixes), `/squad-fleet` creates one git worktree per task on its own branch and runs full `/happysquad-loop` instances concurrently. Up to `max_parallel` (default 4) children run in flight at any time. The fleet orchestrator:

- Tracks each child in `.happysquad/fleets/<fleet-id>/fleet.json`.
- Never auto-merges branches — the user owns merge timing.
- Surfaces an aggregate report with PASS / BLOCKED counts, suggested merge commands, and BLOCKED.md pointers for failed tasks.
- A BLOCKED child does not stall the fleet — others keep going.

Wiki ingests at the end of a fleet are intentionally serialized (one at a time) because they share `knowledge/wiki/index.md`. Everything else parallelizes.

For a **continuous** drain of a ticket queue rather than a one-shot batch, `/squad-drain` runs the tracker frontier serially (`--max=1` by default), pumping as blockers clear, and — unlike `/squad-fleet` — exits silently on an empty frontier with no interactive prompts. That makes it safe to wrap in the built-in loop: `/loop 5m /squad-drain` keeps a standing watch, draining whatever is `ready-for-agent` on each tick and no-op'ing when the queue is empty. Requires a configured `docs/agents/issue-tracker.md` (Matt Pocock `/to-tickets`).

## Cross-session resume

All squad state lives on disk in `.happysquad/` (and `knowledge/` for the wiki), inside your repo — not in any session-scoped scratch space. So **closing and reopening a session never loses progress.**

When you come back:

- A **SessionStart hook** runs a tiny check against `.happysquad/`. If there's in-progress work, it prints a one-line nudge ("you have a dev-loop at iteration 2 — run /squad-resume"). If there's nothing to resume, it prints nothing and costs zero tokens.
- **`/squad-resume`** scans every state file (`state.json`, brainstorm `session.json`, fleet `fleet.json`), finds the most recently updated work that isn't COMPLETE/BLOCKED, and continues it from exactly where it stopped. If multiple things are in progress, it asks which to resume.
- Each mode also self-resumes: re-running `/happysquad-loop`, `/brainstorm`, or `/squad-fleet` detects in-progress state and offers resume / restart / new.

BLOCKED runs are never auto-resumed — they need a human decision, so `/squad-resume` surfaces them and points at the `BLOCKED.md` instead of silently retrying.

> Hook support varies by environment. If the SessionStart nudge doesn't appear, `/squad-resume` and `/squad-status` always work — they read the same on-disk state directly.

## The stack detector

The first time `/happysquad-loop` or `/brainstorm` runs in a project, the detector scans the repo (manifests → configs → conventions → sampled source) and writes `.happysquad/stack-profile.md` + `.happysquad/stack-profile.json`. Subsequent runs read the profile and pass per-agent skill recommendations to each agent at dispatch time:

```
architecter receives → fastendpoints, api-contract-design, react-vite-frontend
implementer receives → fastendpoints, react-vite-frontend
tester receives      → engineering:testing-strategy
reviewer receives    → engineering:code-review, security-review
```

You can also run `/squad-detect` manually to refresh the profile after upgrading a major framework version or adopting a new pattern. The profile lists detected gaps (capabilities where no installed skill matches) so you know what to install or build next.

The profile is read-only with respect to the project — it never writes to your source code. It only reads manifests, configs, and a small sample of source files.

Alongside the stack scan, setup also checks for a `CLAUDE.md` (repo root or `.claude/CLAUDE.md`). Claude Code auto-loads it into every agent's context, so a project that documents its build/test commands, code style, and conventions there gives the squad a sharper starting point. If none exists, the first `/happysquad-loop` or `/brainstorm` nudges you once — generate one via `/init`, skip permanently, or skip for now. It's advisory and never blocks the loop; a permanent skip is remembered in `.happysquad/.claude-md-nudged`.

## Team assembly

`/squad-assemble <spec file or requirement text>` analyzes a spec before any code is touched and recommends how to run the loop: review mode, which specialists to force on/off, per-agent models, and whether to enable external-executor roles. It writes `.happysquad/team-plan.json` (machine-readable) + `.happysquad/team-plan.md` (rationale), shows a summary, then asks you to **Approve / Edit / Reject** — nothing takes effect until you approve it.

Claude agents remain the primary team. External executors (`glm`, canonical; `opencode run`, alternate — both hit the same backend) are limited to exactly three roles, never parallel co-implementers:

- **Mechanical offload** — cheap boilerplate/rename/formatting/docs tasks the architecter tagged `[mechanical]`.
- **Advisory cross-review** — a second-opinion diff review written to `reviews/external.md`; the chief reviewer treats it as an untrusted hint with zero verdict weight, never a vote.
- **Quota fallback** — runs a phase through the external model after repeated rate-limit/overload failures instead of stalling into BLOCKED.

An **approved** team plan's `review_mode`, `models`, and `config_overrides` take precedence over `.happysquad/config.json` for that run. An absent or unapproved plan means the loop behaves exactly as before — config.json alone governs.

## Planning pipeline — Matt Pocock skills (optional)

happysquad executes one well-defined task. For work that's bigger, vaguer, or needs to span sessions, chain it behind the [Matt Pocock](https://www.aihero.dev) skill suite (`/ask-matt`), which owns the upstream phases happysquad skips or does weakly — sharpening the requirement, decomposing it, sizing it to one context window.

```
wayfinder        huge/unclear → decision-ticket map (one ticket per session, fog-of-war)
  → grill-with-docs   interview the human → sharp requirement (+ CONTEXT.md / ADRs)
  → to-spec / to-prd
  → to-tickets   vertical tracer-bullet slices, each ≤ one context window, labelled ready-for-agent
    → /squad-fleet    each frontier ticket → one happysquad-loop in its own worktree
```

Where happysquad plugs in: **the executor at the end.** Every `to-tickets` slice is one `ready-for-agent` task — exactly what `/happysquad-loop` (one slice) or `/squad-fleet` (the whole frontier in parallel) consumes. `/squad-fleet` reads the tracker frontier directly when `docs/agents/issue-tracker.md` is configured, so `to-tickets` → `/squad-fleet` is a clean handoff with no retyping.

Why this makes work better:

- **Right layer, right tool.** `to-tickets` cuts *vertical* feature slices across every layer; happysquad's architecter then splits a slice into *horizontal* workstreams (backend / frontend) internally. They compose, they don't compete.
- **Sharp input.** happysquad's biggest failure mode is an underspecified task; `grill-with-docs` fixes that at the source.
- **One context per unit.** Matt's suite is built around clearing context between units of work; happysquad's orchestrator matches with its own context gate (see the squad-loop skill).

Two stores to keep in sync: Matt writes `CONTEXT.md` + ADRs; happysquad's wiki lives in `knowledge/`. Ingest ADRs into the wiki (`/wiki-ingest`) so there's one source of truth. These are a separate plugin — install/enable independently; happysquad runs standalone without them.

## The brainstorm session

Three rounds, structured so every voice gets heard before any commitment is made:

```
ROUND 1 — Divergent POV (parallel, all 5 agents)
  each agent writes an independent perspective: product framing,
  architectural shape, implementation feasibility, testability, risk surface.

ROUND 2 — Cross-review (parallel, all 5 agents)
  each agent reads the other four R1 notes and responds: where they agree,
  where they disagree, what new questions arise, what changed in their position.

ROUND 3 — Synthesis + sign-off
  architecter writes a single `consensus.md` capturing the agreed solution,
  trade-offs considered, dissents recorded, open questions.
  The other 4 agents read it and write APPROVE or DISSENT with reasoning.

  Convergence:
    4/4 APPROVE     → full-consensus → recommend /happysquad-loop
    1/4 DISSENT     → minor-dissent  → surface fix-suggestion to user
    2+/4 DISSENT    → major-dissent  → surface, suggest 4th round only if asked
```

Brainstorms output to `.happysquad/brainstorms/<session-id>/`. After the session, the orchestrator **always asks** before piping the consensus into `/happysquad-loop` — you stay in the driver's seat.

Quick variants:
- `/brainstorm --rounds=2` skips cross-review (cheaper, shallower).
- `/brainstorm --quick` runs only the product agent — pressure-tests whether a requirement is clear enough to start.

## The loop

```
ARCHITECT ─▶ IMPLEMENT ─▶ TEST ─▶ REVIEW ─┬─▶ COMPLETE   (verdict PASS)
                                          ├─▶ IMPLEMENT  (reviewer routes to implementer)
                                          ├─▶ TEST       (reviewer routes to tester)
                                          └─▶ ARCHITECT  (design needs rework)

Iteration > cap (default 5) ─▶ BLOCKED with a structured report.
```

The reviewer is the only agent that fails the loop. Its verdict + `next` field decide where the next iteration goes.

**Evidence-based gates.** Completion markers are claims, not facts. Before every transition out of an implement/test state the orchestrator re-runs the implementer's build commands and the tester's test commands itself, reads coverage from the coverage tool's report file (never from prose), and requires **red→green proof** — every new AC/bugfix test must be shown to fail at the run's `base_ref` (via a throwaway worktree) before it counts. Verified values land in `evidence-check.md` and `state.json`; a claim that doesn't reproduce routes the loop back to the claiming agent.

**Inner fix loop.** Every review issue carries a `Verify` command (exit code 0 = fixed; `manual` when only judgment can confirm). When a FAIL routes to implementer/tester and every blocker is machine-checkable, the orchestrator skips the full pipeline round: fix agent → run the per-finding checks (up to `inner_cap`, default 2 passes) → evidence gate → a **delta review** that confirms the fixes first-hand instead of re-deriving everything. A single `manual` blocker falls back to the full round.

**Convergence detection.** The reviewer marks every issue `new` or `repeat` against its previous review. A blocker that survives two fix rounds escalates to the architecter instead of bouncing back a third time; a blocker that recurs after a redesign — or two consecutive rounds with zero resolved blockers — stops the loop as BLOCKED early, with a convergence analysis (rounds seen, routes tried) ready to become a wiki lesson. The round cap is the backstop, not the detector.

## Defaults

- **Round cap:** 5
- **Inner fix-loop cap:** 2 verify-checked fix passes per review round
- **Coverage threshold:** 80%
- **Models:** opus for architecter/reviewer, sonnet for implementer/tester

Override in `.happysquad/config.json` at the repo root:

```json
{
  "cap": 10,
  "inner_cap": 2,
  "coverage_threshold": 85,
  "models": {
    "architecter": "opus",
    "implementer": "sonnet",
    "tester": "haiku",
    "reviewer": "opus"
  }
}
```

## The wiki — institutional memory

A Karpathy-style LLM wiki at the repo root, separate from `.happysquad/` working files:

```
knowledge/
├── raw/                       # immutable ingested sources
│   └── <topic>/<dated>.md     # designs, reviews, brainstorm consensuses, BLOCKED reports, external docs
└── wiki/                      # LLM-compiled articles (synthesized, cross-linked, cascade-updated)
    ├── index.md
    ├── log.md
    ├── decisions/             # ADRs (mostly fed by brainstorm consensuses)
    ├── lessons/               # rules from BLOCKED + recurring review issues
    ├── patterns/              # reusable technical patterns
    ├── runbook/               # operational procedures
    └── subsystems/            # per-subsystem architecture + known issues
```

The wiki compounds: every successful `/happysquad-loop` and `/brainstorm` ends with an offer to ingest its artifacts. Accepting routes them to the appropriate topic — `design.md` → `subsystems/*`, `BLOCKED.md` → `lessons/*`, `consensus.md` → `decisions/*`.

**Read-back by the agents:**

- `architecter` reads `subsystems/*`, `patterns/*`, `decisions/*` before designing → fewer rounds.
- `reviewer` reads `lessons/*` before flagging issues → catches recurring mistakes immediately.
- `product` reads `decisions/*` before pressure-testing scope → doesn't re-open settled questions.

The wiki is plain markdown with relative links. Point an [Obsidian](https://obsidian.md) vault at `knowledge/` for graph view, backlinks, and full-text search — or just read the files in any editor. The skill never depends on Obsidian-specific syntax.

## File layout the squad produces

```
.happysquad/                              # operational working files (can be .gitignored)
├── state.json                           # current dev-loop run, iteration, history
├── config.json                          # optional overrides (cap, models, parallel_isolation, max_parallel)
├── stack-profile.md                     # human-readable stack scan + per-agent skills
├── stack-profile.json                   # structured signals consumed by the orchestrator
├── fleets/<fleet-id>/                   # fleet roll-ups
│   ├── fleet.json
│   ├── tasks.md
│   └── aggregate-report.md
├── worktrees/<fleet-id>/<slug>/         # per-task worktree (deleted on cleanup)
├── runs/
│   └── 20260520-103045-add-auth/        # one directory per dev-loop task
│       ├── design.md                    # from architecter (incl. Workstreams + Ownership map)
│       ├── implementation.md            # from implementer (single-workstream runs)
│       ├── test-report.md               # from tester (single-workstream runs)
│       ├── test-output.txt              # full runner output (evidence; per-workstream in parallel runs)
│       ├── workstreams/<name>/          # per-workstream artifacts (parallel runs)
│       │   ├── implementation.md
│       │   ├── test-report.md
│       │   └── ownership-gap.md         # only if an agent hit a gap
│       ├── evidence-check.md            # orchestrator's verified build/test/coverage results (evidence gate)
│       ├── conflict-check.md            # written by orchestrator before review (parallel runs)
│       ├── review.md                    # from reviewer (includes conflict-gate verdict)
│       ├── feedback.md                  # written by orchestrator between iterations
│       └── BLOCKED.md                   # only if the round cap was hit
└── brainstorms/
    └── 20260520-114500-bs-export/       # one directory per brainstorm session
        ├── topic.md                     # the input requirement
        ├── session.json                 # session metadata + state
        ├── round1-{agent}.md            # one per agent (5 files)
        ├── round2-{agent}.md            # one per agent (5 files)
        ├── consensus.md                 # architecter's synthesis
        └── signoffs.md                  # aggregated APPROVE/DISSENT

knowledge/                               # the project wiki (commit this)
├── raw/<topic>/...
└── wiki/...
```

Both `state.json` and `session.json` are audit logs. The wiki is the durable, compounding artifact.

## How agents communicate

Agents do **not** chat. They communicate through artifact files:

- `architecter` writes `design.md` → `implementer` reads it.
- `implementer` writes code + `implementation.md` → `tester` reads them.
- `tester` writes tests + `test-report.md` → `reviewer` reads everything.
- `reviewer` writes `review.md` with a routing decision → orchestrator extracts blocker/major issues into `feedback.md` for the next iteration.

Each agent ends with a completion marker line (`DESIGN_READY: …`, `IMPLEMENTATION_READY: …`, `TESTS_READY: …`, `REVIEW_READY: …`) that the orchestrator uses as the hand-off signal. Markers are treated as claims: the orchestrator verifies them at the evidence gate (re-running recorded commands, reading the coverage report file) before transitioning.

## Token efficiency

- Heavy reasoning runs on opus; mechanical writing runs on sonnet.
- Subagents receive **file paths**, not file contents. Each agent Reads only what it needs.
- Verbose outputs (test logs, build logs) go to disk; agents reference paths instead of pasting blobs.
- The orchestrator holds state in working memory and writes state.json once per transition.

## Usage

**Onboarding a new repo to the squad — one-time:**

```text
/squad-detect
```

Scans manifests, configs, and conventions. Writes `stack-profile.md` with per-agent skill recommendations. (You can skip this — `/happysquad-loop` will run it automatically the first time.)

**Clear requirement → straight to the loop:**

```text
/happysquad-loop add multi-tenant API key auth to the billing service
```

Expected end-state: PASS verdict, working code + tests committed-ready, coverage ≥ 80%, and a one-line suggested commit message for you to apply.

**Multiple independent features → fleet mode:**

```text
/squad-fleet
```

You'll be asked to list tasks (or point at a file). The squad creates one git worktree per task on a `fleet/<fleet-id>/<slug>` branch, runs `/happysquad-loop` in each concurrently (up to `max_parallel`, default 4), and produces an aggregate report with merge suggestions.

**Vague requirement → brainstorm first:**

```text
/brainstorm we need to let customers export their own data
```

Five agents discuss for 3 rounds in parallel, write a consensus, and ask whether to ingest it into the wiki as a Decision and proceed to `/happysquad-loop`. You see the full disagreement before any code is touched.

**Cold start on a new subsystem → ask the wiki first:**

```text
/wiki-ask what do we know about authentication in this project?
```

Returns a synthesized answer with citations to `subsystems/*.md`, `lessons/*.md`, and `decisions/*.md` articles. Useful before opening a `/brainstorm` to make sure you're not re-treading ground.

If the dev-loop hits BLOCKED, read `.happysquad/runs/<run-id>/BLOCKED.md` — and ingest it into the wiki as a `lessons/<slug>.md` entry. Every BLOCKED that isn't captured as a lesson is a future wasted loop. Sometimes the right escalation is `/brainstorm` to re-examine the requirement.

## Integration

- **Git:** the squad uses `git status`, `git diff`, `git log` for situational awareness. It does **not** commit, branch, push, or stash unless the task explicitly requests it.
- **External tools:** none required. The plugin is self-contained — all communication happens through local files in `.happysquad/`.

## License

MIT
