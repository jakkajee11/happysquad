---
name: squad-loop
description: |
  Orchestrates the dev-squad's four-agent hand-off loop (architecter → implementer → tester → reviewer)
  for a software-development task. Defines the state machine, per-state inputs and outputs, the routing
  table the reviewer drives, the round cap, and the BLOCKED escalation. Trigger when the user runs
  /dev-squad-loop, asks to "run the squad", "start the dev loop", "iterate until pass", or invokes any of
  /architect, /implement, /test, /review individually.
---

# Squad Loop

The orchestrator that drives the four dev-squad agents through one task until the reviewer says PASS or the round cap is hit.

## State machine

```
   START ─▶ ARCHITECT ─▶ (parallel?) ──┬──── no ───▶ IMPLEMENT ──▶ TEST ──▶ CONFLICT_GATE ──▶ REVIEW ──┐
                                       │                                                              │
                                       └──── yes ──▶ PARALLEL_IMPLEMENT (DAG waves) ──▶              │
                                                    PARALLEL_TEST (DAG waves) ──▶                    │
                                                    CONFLICT_GATE ──▶ REVIEW ──────────────────────▶ ┤
                                                                                                     │
                                                                                                     ├─▶ COMPLETE
                                                                                                     ├─▶ (route=architecter) ─▶ ARCHITECT (workstreams may change)
                                                                                                     ├─▶ (route=implementer,workstreams=…) ─▶ PARALLEL_IMPLEMENT (subset)
                                                                                                     └─▶ (route=tester,workstreams=…) ─▶ PARALLEL_TEST (subset)

If iteration counter > cap (default 5) → BLOCKED.
```

The `(parallel?)` decision comes from the architecter's `DESIGN_READY: … workstreams=N parallel=<true|false>` marker. `parallel=false` collapses to the linear state machine (just IMPLEMENT → TEST → REVIEW).

Every transition out of an IMPLEMENT/TEST state passes through the **evidence gate** (§3) before the next state runs: completion markers are claims, and the orchestrator verifies them against re-run commands and report files first.

A FAIL routed to implementer/tester where **every blocker has a machine-checkable `Verify` command** takes the **inner fix loop** (§5) — fix → per-finding verify → delta review — instead of the full pipeline.

## Per-state contract

| State              | Agent(s)               | Reads                                            | Writes                                       | Completion marker         |
|--------------------|------------------------|--------------------------------------------------|----------------------------------------------|---------------------------|
| ARCHITECT          | architecter            | task, repo, prior design+feedback (if any)       | `design.md` (with Workstreams + Ownership)   | `DESIGN_READY: … workstreams=N parallel=<bool>` |
| IMPLEMENT (single) | implementer            | `design.md`, `feedback.md` (if any), repo        | source files, `implementation.md`            | `IMPLEMENTATION_READY: …` |
| PARALLEL_IMPLEMENT | N implementers (parallel per wave) | per-workstream design + ownership      | per-workstream source files + `workstreams/<name>/implementation.md` | `IMPLEMENTATION_READY: … workstream=<name>` × N |
| TEST (single)      | tester                 | `design.md`, `implementation.md`, repo, feedback | test files, `test-report.md`                 | `TESTS_READY: …`          |
| PARALLEL_TEST      | N testers (parallel per wave) | per-workstream impl + ownership       | per-workstream test files + `workstreams/<name>/test-report.md` | `TESTS_READY: … workstream=<name>` × N |
| EVIDENCE_GATE      | orchestrator (after every IMPLEMENT/TEST state) | commands + report paths recorded in `implementation.md` / `test-report.md`, repo | `evidence-check.md` (one section per gate) | (internal — no agent)     |
| CONFLICT_GATE      | orchestrator           | design Ownership map, git diff sets, build       | `conflict-check.md`                          | (internal — no agent)     |
| RISK_DETECT        | orchestrator (split-on-risk only) | git diff --name-only + diff content    | `risk-detection.md`                          | (internal — no agent)     |
| REVIEW (specialists, split / split-on-risk) | 0-4 specialists in parallel: security-reviewer, performance-reviewer, requirement-reviewer, standard-reviewer | design + diff + per-axis context | `reviews/<axis>.md` per dispatched specialist | `<AXIS>_REVIEW_READY: …` per specialist |
| REVIEW (chief)     | reviewer (chief)       | design + all workstream artifacts + conflict-check + evidence-check + risk-detection + dispatched specialists' review files + diff | `review.md` (aggregated) | `REVIEW_READY: …`         |

All paths are under `.dev-squad/runs/<run-id>/` at the repo root.

## State file

Orchestrator maintains `.dev-squad/state.json` (or `.dev-squad/runs/<run-id>/state.json` when this run is a fleet child — see fleet-orchestrator skill):

```json
{
  "run_id": "20260520-103045-add-api-key-auth",
  "task": "<one-line task description>",
  "base_ref": "<git rev-parse HEAD at run start — null if the repo has no commits>",
  "mode": "parallel",
  "parent_fleet_id": null,
  "worktree": null,
  "current_state": "PARALLEL_IMPLEMENT",
  "iteration": 1,
  "cap": 5,
  "coverage_threshold": 80,
  "workstreams": [
    {
      "name": "backend",
      "owned_files": ["Backend/Endpoints/Auth/CreateApiKey.cs", "..."],
      "depends_on": [],
      "ac_covered": ["AC-1", "AC-2"],
      "implement_status": "complete",
      "test_status": "in_progress",
      "implementer_marker": "IMPLEMENTATION_READY: …",
      "tester_marker": null
    },
    {
      "name": "frontend",
      "owned_files": ["Frontend/src/..."],
      "depends_on": ["backend"],
      "ac_covered": ["AC-3", "AC-4"],
      "implement_status": "pending",
      "test_status": "pending"
    }
  ],
  "conflict_check": { "status": "pending", "violations": [] },
  "history": [
    { "state": "ARCHITECT", "iteration": 1, "result": "ok", "workstreams_planned": 2 },
    { "state": "PARALLEL_IMPLEMENT", "iteration": 1, "wave": 1, "workstreams": ["backend"], "result": "ok" },
    { "state": "PARALLEL_TEST", "iteration": 1, "wave": 1, "workstreams": ["backend"], "result": "ok", "verified": { "tests": "pass", "coverage": 84.2 } },
    { "state": "REVIEW", "iteration": 1, "verdict": "FAIL", "next": "implementer", "blockers": 2, "resolved": 0, "recurring": 0 },
    { "state": "INNER_FIX", "iteration": 2, "inner_pass": 1, "checks": { "R-1": "pass", "R-2": "pass" } }
  ],
  "started_at": "2026-05-20T10:30:45Z",
  "updated_at": "2026-05-20T11:12:09Z"
}
```

`mode` is one of `single` (single workstream), `parallel` (multi-workstream within one task), or `fleet-child` (this run was spawned by /squad-fleet and has a sibling running in another worktree).

Update this file after every state transition. Never delete history.

## Configuration

Read `.dev-squad/config.json` if present. Defaults if missing:

```json
{
  "cap": 5,
  "inner_cap": 2,
  "coverage_threshold": 80,
  "models": {
    "architecter": "opus",
    "implementer": "sonnet",
    "tester":      "sonnet",
    "reviewer":    "opus"
  }
}
```

Honor the `models` block when launching subagents — pass the configured model to the Agent tool's `model` parameter.

## Orchestration protocol

### 1. Setup

When invoked:

1. If `<task>` is empty, ask the user for the task description with AskUserQuestion. Do not invent a task.
2. **Stack profile check** — look for `.dev-squad/stack-profile.md`:
   - If absent → tell the user "First run in this project — scanning stack (one-time setup)" and invoke the `stack-detector` skill to produce `stack-profile.md` and `stack-profile.json` before continuing.
   - If present → read `stack-profile.json` to get per-agent skill recommendations. Check whether any manifest file (package.json, *.csproj, go.mod, Cargo.toml, etc.) has a `mtime` newer than the profile's `generated_at` — if yes, prompt: "Project manifests changed since last scan. Refresh stack profile? — yes / no / never-ask-again". Honor the answer.
3. **Project conventions check (CLAUDE.md)** — the squad's agents work best when the project ships a `CLAUDE.md` (build/test commands, code style, conventions); Claude Code auto-loads it into every agent's context. Look for `CLAUDE.md` at the repo root or `.claude/CLAUDE.md`:
   - If present → nothing to do; it is already in context.
   - If absent AND `.dev-squad/.claude-md-nudged` does not exist → tell the user once: "No CLAUDE.md found — the squad runs better with one (project conventions, build/test commands, code style). Agents read it automatically." Then AskUserQuestion: "Generate one now (runs /init), then continue" / "Continue without — don't ask again" / "Continue without — ask next time". Honor the answer: on generate, run `/init` then continue; on don't-ask-again, write `.dev-squad/.claude-md-nudged` and continue; on ask-next-time, continue without writing the marker. Never block the loop on this — it is advisory.
4. Generate `run_id` = `YYYYMMDD-HHMMSS-<slug-of-first-6-task-words>`.
5. Create `.dev-squad/runs/<run-id>/`.
6. Load or create `.dev-squad/state.json` and `.dev-squad/config.json`.
7. Record `base_ref` = `git rev-parse HEAD` in state.json (`null` if the repo has no commits yet), and note a dirty tree if `git status --porcelain` is non-empty. Every "changed since loop start" diff, the conflict gate, and the tester's red→green proof measure against this ref.
8. Set `current_state = ARCHITECT`, `iteration = 1`.

### 2. State step

For each state, do this in order:

1. Update state.json with the new `current_state` and bump `updated_at`.
2. Launch the corresponding agent with the Agent tool, passing:
   - the task description
   - the run-id
   - the iteration counter
   - file paths for any inputs the agent needs (design.md, feedback.md, etc.)
   - the run's `base_ref` (the tester needs it for the red→green proof)
   - the model from config
   - **the per-agent skill list from `stack-profile.json`** (under `recommended_skills.<agent-name>`) so the agent loads the right stack-specific skills at the start of its run
3. Wait for the agent's completion marker line (malformed/missing → see "Marker protocol & failure handling").
4. For IMPLEMENT/TEST states, run the **evidence gate** (§3) on the marker's claims. Never transition on an unverified claim.
5. Append an entry to `history` in state.json, including the gate's `verified` values when present.
6. Transition per the rules below.

### 3. Evidence gate

Completion markers are **claims, not facts**. Verify every claim against evidence, record the verified values, then transition. Append each gate's result to `.dev-squad/runs/<run-id>/evidence-check.md` (one section per gate per iteration: what was claimed, what was verified, verdict).

**After IMPLEMENT / each PARALLEL_IMPLEMENT wave:**

1. Read the build/lint/type-check command(s) the implementer recorded verbatim in implementation.md.
2. Re-run them (scoped to the workstream in parallel mode). The exit code is the truth — not the implementer's summary.
3. On mismatch (claimed green, actually red): write the discrepancy (command, exit code, output tail) to feedback.md, `iteration += 1`, re-dispatch the same implementer/workstream. Never hand the tester a build that only claims to compile.

**After TEST / each PARALLEL_TEST wave:**

1. Re-run the exact test command(s) recorded in test-report.md (workstream-scoped in parallel mode). Compare the real exit code and pass/fail counts against the claimed `status`.
2. Read coverage from the coverage tool's report file — the tester records its path in test-report.md (e.g. `coverage/coverage-summary.json`, `coverage.xml`, `lcov.info`). The verified number from that file is what the REVIEW coverage gate uses; the marker's `coverage=` field is only a claim. No report file → record coverage as `"unverified"` (a TEST finding for the reviewer, not a silent pass).
3. Confirm test-report.md contains the `## Red→green evidence` section covering the new AC/bugfix tests (see the tester agent). A missing section — or any test recorded as *passing* at `base_ref` — means the tests don't prove the change: write the discrepancy to feedback.md, `iteration += 1`, re-dispatch the tester.
4. Record `"verified": { "tests": "<pass|fail>", "coverage": <percent | "unverified"> }` in the history entry.

Evidence-gate rules:

- A claim that doesn't reproduce is never "close enough" — route it back. A loop that trusts claims converges on paperwork, not on working code.
- Full command output goes to disk (test-output.txt or a file referenced from evidence-check.md), not into your context. Quote at most the last ~20 lines inline, and only on failure.
- Manual entry points (`/implement`, `/test`, `/review`) have no orchestrator, so the gate doesn't run; the reviewer treats unverified numbers as claims (see its evidence-check input).

### 4. Transition rules

After `ARCHITECT`, parse the marker `DESIGN_READY: … workstreams=N parallel=<bool>`:

- If `parallel=false` or `workstreams=1` → next state = `IMPLEMENT` (single mode).
- If `parallel=true` → next state = `PARALLEL_IMPLEMENT` (multi mode). Also load the Workstreams + Ownership map from design.md into `state.json.workstreams`.

After `IMPLEMENT` (single) → next state = `TEST`. Always.
After `TEST` (single) → next state = `CONFLICT_GATE` (which becomes a no-op for single runs — see below). Then `REVIEW`.

After `PARALLEL_IMPLEMENT` → next state = `PARALLEL_TEST`. (Wave-based — see Parallel scheduling below.)
After `PARALLEL_TEST` → next state = `CONFLICT_GATE`. Then `REVIEW`.

After `REVIEW`:
- If `verdict=PASS` → next state = `COMPLETE`. Exit loop, report success.
- If `verdict=FAIL` and `next=architecter` → write reviewer's issues to `feedback.md`, `current_state = ARCHITECT`, `iteration += 1`. The architecter may revise workstreams. (Design rework never takes the inner fix loop.)
- If `verdict=FAIL` and `next=implementer` or `next=tester` → check inner-loop eligibility (§5): if every blocker in review.md has a machine-checkable `Verify` command, run the **inner fix loop** instead of a full pipeline round. Otherwise:
  - `next=implementer` and `mode=single` → `current_state = IMPLEMENT`, `iteration += 1`.
  - `next=implementer` and `mode=parallel` → `current_state = PARALLEL_IMPLEMENT`, but **only re-dispatch the workstreams listed in the reviewer's `workstreams` field** (subset re-dispatch). `iteration += 1`.
  - `next=tester` → analogous to implementer.

#### Convergence check — on every FAIL, before routing

The round cap (§10) is the backstop, not the detector. After each FAIL review, compare its issues against the previous review via the reviewer's `Recurrence` column:

- `resolved` = blockers from the previous review that no longer appear.
- `recurring` = blockers marked `repeat`.

Then apply, in order:

1. **Second repeat → escalate the route.** A blocker on its second repeat (same defect in three consecutive reviews) never goes back to the agent that failed it twice. The reviewer should already have routed it to `architecter`; enforce the override if it didn't, and log the override in history.
2. **Repeat after redesign → BLOCKED now.** A blocker that recurs *after* an architecter round it triggered has exhausted every route. Go straight to the BLOCKED protocol (§10) — don't burn the remaining rounds.
3. **Zero-progress round.** If `resolved` is empty — the fix round changed nothing the reviewer could credit — route to `architecter` regardless of the reviewer's `next`. Two consecutive zero-progress rounds → BLOCKED.

Record convergence data in each REVIEW history entry: `"blockers": N, "resolved": N, "recurring": N`. When convergence triggers BLOCKED, BLOCKED.md must include the Convergence analysis section (§10).

### 5. Inner fix loop (per-finding verify)

A review FAIL routed to `implementer` or `tester` does not have to cost a full pipeline round (fix agent → tester → conflict gate → full review). Every issue row in review.md carries a `Verify` command (see the reviewer agent) whose exit code 0 proves that issue is fixed. When **every blocker is machine-checkable** (none marked `manual`), take the cheap path:

1. Write feedback.md as usual — each copied issue row keeps its `Verify` command. `iteration += 1` (the delta review below is this round's REVIEW). Set `current_state = INNER_FIX` and track `inner_pass` in state.json.
2. Dispatch the fix agent(s). If blockers route to both implementer and tester, dispatch the implementer first, then the tester (tests may depend on the fixed code). Subset workstreams apply as in the outer loop.
3. When the agent returns, run each blocker's `Verify` command yourself. Record per-check results in evidence-check.md (`inner pass N: R-1 pass, R-2 fail`) and in the history entry.
4. Any check fails → append the failing checks to feedback.md and re-dispatch the same agent. At most `inner_cap` (default 2) inner passes; if checks still fail after that, fall back to the full outer pipeline (IMPLEMENT/TEST → … → full REVIEW) for this round — the finding is evidently not as mechanical as it looked.
5. All checks pass → run the full evidence gate (§3): re-run the build and the whole test suite — a targeted fix can break things the per-finding checks don't see. If the suite fails on tests that legitimately need updating, dispatch the tester with the failures before proceeding.
6. Then CONFLICT_GATE (parallel runs — fixes must stay inside ownership) → dispatch the chief reviewer with `mode=delta`: it confirms each fixed blocker first-hand, scans the fixed files for regressions, and re-issues the verdict. Specialists are NOT re-dispatched unless the fix touched files matching new risk patterns (run risk detection on the fix's changed files only).

The inner loop is a shortcut, not a bypass: the delta review still issues the verdict, the round cap counts every review round, and a single `manual` blocker disqualifies the shortcut entirely.

### 6. Parallel scheduling

When entering `PARALLEL_IMPLEMENT` or `PARALLEL_TEST`:

1. Build the DAG from `workstreams[i].depends_on`.
2. Compute waves via topological sort: wave 1 = all workstreams with no unsatisfied deps; wave 2 = workstreams unblocked by wave 1; etc.
3. For each wave (sequentially):
   a. Dispatch **all workstreams in this wave in a single message with multiple Agent tool calls**. This is mandatory — separate messages waste wall-clock time and provide no benefit.
   b. Each Agent call passes: task, run-id, iteration, workstream name, owned_files list, paths to design.md and feedback.md (if any), model from config, recommended skills from stack-profile.
   c. Wait for ALL completion markers in this wave, then run the evidence gate (§3) on each workstream in the wave, before starting the next wave — dependents must never build on an unverified claim.
   d. Update state.json per-workstream as markers arrive.
4. If any workstream returns `OWNERSHIP_GAP` instead of READY → halt the wave, write feedback aggregating all ownership gaps from this wave, route back to ARCHITECT to update the ownership map. `iteration += 1`.

### 7. Conflict-detection gate

Run after `PARALLEL_TEST` (and as a no-op pass-through after single-mode `TEST` — write a trivial `conflict-check.md` saying "single-workstream run, no conflict surface").

For multi-workstream runs:

1. **Ownership compliance** — for each workstream, run `git diff --name-only <base_ref> --` (base_ref from state.json) scoped to its files. Confirm every file changed by workstream W is in `state.json.workstreams[W].owned_files`. Any file outside is a CONFLICT.
2. **Disjoint diff sets** — confirm the per-workstream diff sets do not overlap. Overlap is a CONFLICT.
3. **Integration build** — run the project's full build/test command once across the merged state. If `npm run build`, `dotnet build`, etc. succeed individually but fail integrated, that's a CONFLICT.
4. Write `.dev-squad/runs/<run-id>/conflict-check.md` with one of:
   - `Status: CLEAN` + a short table of per-workstream diff counts.
   - `Status: VIOLATIONS` + a list of violations (file, workstream(s) involved, reason).

If violations exist:
- Re-route directly to ARCHITECT (skip REVIEW). The partition is wrong; the design's Ownership map needs revision. `iteration += 1`.

If clean:
- Proceed to REVIEW. The reviewer reads conflict-check.md as part of its inputs.

### 8. Worktree fallback

If at ARCHITECT, the architecter outputs a design with overlapping ownership (or a Conflict surface section with non-empty rows) AND the user/orchestrator decides parallelism is still desired:

1. Create a git worktree per workstream at `.dev-squad/worktrees/<run-id>/<workstream>/`.
2. Each parallel implementer + tester runs inside its worktree (pass the worktree path as the working directory to the Agent tool).
3. After PARALLEL_TEST, the orchestrator **merges** worktrees back into the main repo:
   a. For each workstream's worktree, run `git diff --no-color` to capture changes.
   b. Apply all diffs to the main repo in dependency order.
   c. If any patch fails to apply (true conflict), abort the merge and route to ARCHITECT — the partition is genuinely overlapping and must be redesigned.
4. CONFLICT_GATE runs on the merged main repo. The integration build catches issues the worktrees couldn't see in isolation.

Worktree mode is opt-in via `.dev-squad/config.json`:

```json
{ "parallel_isolation": "ownership-then-worktree" }
```

Default is `ownership-then-worktree` (try ownership first, fall back to worktree on overlap). Other valid values:
- `ownership-only` — never use worktrees; conflict surface always routes back to architecter.
- `always-worktree` — every parallel run uses worktrees, even when ownership is disjoint. Higher setup cost, stronger isolation.

### 9. REVIEW state — mode dispatch

The REVIEW state runs after CONFLICT_GATE. It supports three modes set in `.dev-squad/config.json`:

```json
{ "review_mode": "split-on-risk" }
```

Valid values: `single`, `split`, `split-on-risk`. Default is `split-on-risk`.

#### Mode: single

1. Dispatch the chief `reviewer` agent with `mode=single` and `delegated_specialists=[]`.
2. Wait for `REVIEW_READY` marker.
3. Done.

#### Mode: split

1. Dispatch **four specialist reviewers in parallel** in a single message with multiple Agent tool calls:
   - `security-reviewer`
   - `performance-reviewer`
   - `requirement-reviewer`
   - `standard-reviewer`
2. Wait for all four specialist markers (`SECURITY_REVIEW_READY`, `PERFORMANCE_REVIEW_READY`, `REQUIREMENT_REVIEW_READY`, `STANDARD_REVIEW_READY`).
3. Dispatch the chief `reviewer` with `mode=split` and `delegated_specialists=["security-reviewer","performance-reviewer","requirement-reviewer","standard-reviewer"]`. The chief reads all four review files, dedups across axes, runs TEST + CONFLICT itself, makes final verdict.
4. Wait for `REVIEW_READY` marker. Done.

#### Mode: split-on-risk

Run the **risk detection pass** before dispatch:

1. Compute the changed file list with `git diff --name-only <base_ref>` (base_ref from state.json).
2. Match each file against the risk patterns below. Collect the set of axes flagged.
3. For each flagged axis, dispatch the corresponding specialist reviewer **in parallel with the chief reviewer**, all in one multi-Agent-tool message.
4. Pass the chief reviewer `mode=split-on-risk` and `delegated_specialists=<list of specialists actually dispatched>`. The chief handles non-delegated axes itself, plus always handles TEST + CONFLICT.

#### Risk detection patterns

Match file paths and diff content against these patterns. Multiple matches = multiple specialists dispatched.

**SEC triggers** → dispatch `security-reviewer`:
- File path matches (case-insensitive): `*auth*`, `*authn*`, `*authz*`, `*permission*`, `*role*`, `*token*`, `*secret*`, `*credential*`, `*password*`, `*session*`, `*jwt*`, `*oauth*`, `*saml*`, `*api*key*`, `*encrypt*`, `*decrypt*`, `*hash*`, `*hmac*`, `*crypto*`, `*signature*`
- File path matches: `*payment*`, `*billing*`, `*charge*`, `*invoice*`, `*subscription*`, `*card*`, `*kyc*`
- Diff adds package dependencies — new entries in `package.json` `dependencies`, new `<PackageReference>` in `*.csproj`, new lines in `requirements.txt`, new `[dependencies]` rows in `Cargo.toml`, new `require` blocks in `go.mod`, new lines in `Gemfile`
- Diff touches CORS / CSP / security headers — grep the diff for `cors`, `csp`, `helmet`, `Content-Security-Policy`, `Access-Control-Allow`, `X-Frame-Options`, `Strict-Transport-Security`
- File path matches `*.csproj`, `pom.xml`, `build.gradle` AND a dependency line changed (dependency upgrades can introduce CVEs)
- File path matches migration patterns AND the migration adds fields containing `password`, `token`, `secret`, `email`, `phone`, `ssn`, `credit_card`

**PERF triggers** → dispatch `performance-reviewer`:
- Diff adds database query patterns — grep the diff for `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `FROM`, ORM operations (`.where(`, `.findMany(`, `.toListAsync(`, `Include(`, `JOIN`), or LINQ chains
- File path matches migration patterns: `*migration*`, `*alembic*`, `prisma/schema.prisma`, `*Migration*.cs`
- Diff adds loop structures with database calls (heuristic: `for`/`foreach`/`map`/`forEach` within 20 lines of a query call)
- Diff adds external HTTP / RPC calls — grep for `fetch(`, `axios.`, `httpClient.`, `await http.`, `requests.`, `client.Call`
- Diff modifies caching logic — grep for `cache`, `memo`, `redis`, `memcache`
- File path matches `*queue*`, `*worker*`, `*job*`, `*background*`, `*scheduler*`

**REQ triggers** → never auto-dispatch a specialist; the chief reviewer handles REQ in all modes. (REQ is core to every diff, not risk-conditional. Adding a REQ specialist in split-on-risk doubles cost without adding signal.)

**STD triggers** → never auto-dispatch a specialist; the chief reviewer handles STD in all modes. (STD is mechanical pattern matching; the chief on opus handles it adequately, and a sonnet specialist would mostly duplicate work.)

#### Risk-detection output

The orchestrator writes `.dev-squad/runs/<run-id>/risk-detection.md` summarizing the matches:

```markdown
# Risk detection — run <run-id> iteration <N>

Files changed: <count>

| File                        | Triggers matched              |
|-----------------------------|-------------------------------|
| src/auth.ts                 | SEC (auth pattern)            |
| Backend/Migrations/2026…cs  | PERF (migration), SEC (email field added) |
| package.json                | SEC (dependency added)        |

Specialists dispatched: security-reviewer, performance-reviewer
Chief reviewer handles: REQ, STD, TEST, CONFLICT
```

This file is part of the run's audit trail and gets attached as input to the chief reviewer.

### Specialist output capture & chief first-hand read

- **Capture inline specialist output.** Specialist reviewers are instructed to write `.dev-squad/runs/<run-id>/reviews/<axis>.md`, but some specialist runtimes forbid file writes and return their review as their final assistant message instead. After each specialist returns, check whether its `reviews/<axis>.md` exists; if not, capture the specialist's inline findings into that file verbatim **before dispatching the chief**. The chief always reads files, and the run's audit trail stays complete — no ad-hoc inline handoffs.
- **The chief must read the diff first-hand.** In split / split-on-risk the chief does NOT merely tally delegated specialists' verdicts + green tests and PASS. Cross-cutting correctness defects — identifier-scheme mismatches between setup and teardown (e.g. schedule vs cancel), call/callee agreements, state read/write pairs — live in the seams *between* axes, where no single specialist looks. The chief must run `git diff` and read the changed code itself, citing `file:line` evidence it read, before a PASS verdict. (See wiki lesson `chief-reviewer-reads-the-diff`.) This is the single highest-leverage thing the chief does; delegate-and-tally misses exactly the bugs that ship.

### 10. Round cap

Before transitioning, check `iteration > cap`. If yes — or the convergence check (§4) triggered an early stop:

1. Set `current_state = BLOCKED`.
2. Write `.dev-squad/runs/<run-id>/BLOCKED.md` summarizing:
   - The original task
   - Every reviewer verdict so far (table from history)
   - The current blocking issues
   - Convergence analysis: each recurring blocker with the rounds it appeared in, the routes tried, and the fix attempts that failed — this is the raw material for a `lessons/*` wiki entry
   - A recommended next manual action (e.g., "split the task", "consult human reviewer", "adjust acceptance criteria")
3. Exit the loop and report BLOCKED to the user. Do not silently retry.

## Marker protocol & failure handling

The completion marker is the hand-off contract. Three failure modes, one protocol each — never improvise:

- **Malformed or missing marker.** The agent finished but its final message doesn't match the expected marker format, or the marker names an artifact file that doesn't exist on disk. Do not guess the fields. Re-dispatch the same agent once with: "Your final message must be exactly one line matching `<expected format>` — your artifact file `<path>` {exists|is missing}; finish accordingly." If the second attempt is also malformed → log `{"result": "marker-failure"}` in history and treat the state as FAILED: write feedback.md describing what's missing, `iteration += 1`, route per the normal rules.
- **Agent error / death.** The Agent tool call errors or returns nothing. Retry the dispatch once, verbatim. A second failure → BLOCKED protocol (§10) with the error captured in BLOCKED.md — an infrastructure failure isn't fixable by looping.
- **Marker/evidence contradiction.** The marker claims READY but the evidence gate (§3) disproves it — already handled by §3 (feedback + re-dispatch). Evidence always overrides the marker.

One retry, then escalate. Two identical failures in a row means the problem is systemic (prompt, environment, permissions) — further retries burn tokens without producing new information.

## Manual entry points

Each manual command corresponds to one state. When the user invokes one directly:

- `/architect <task>` → run ARCHITECT only, then stop. Do not auto-advance.
- `/implement` → assumes `.dev-squad/runs/<run-id>/design.md` exists for the current run-id (from state.json), or asks which run to use.
- `/test` → assumes implementation.md exists.
- `/review` → assumes test-report.md exists.

Manual invocations still write to the same state.json so the user can switch between manual and looped modes.

## Feedback file format

When a review fails and the loop routes back, the orchestrator extracts the reviewer's issues into `.dev-squad/runs/<run-id>/feedback.md`:

```markdown
# Feedback for iteration <N+1>
Target agent: <implementer|tester|architecter>
Verdict from iteration <N>: FAIL

## Blocker issues
<copy R-* rows from review.md tagged blocker — including each row's Verify command>

## Major issues (address if cheap)
<copy R-* rows tagged major>

## Failing checks (inner fix loop only)
<present only during §5 inner passes ≥2: the Verify commands that still failed last pass, with their output tails>

## Reviewer summary
<paste the Summary paragraph from review.md>
```

This is the only artifact the next agent reads to know what changed.

## Git etiquette

- The squad reads git freely (`git status`, `git diff`, `git log`).
- Only the implementer and tester write to source files. They do not commit, branch, or push unless the task explicitly says to.
- At the end of a successful loop, do not auto-commit. Print a one-line suggested commit message in the success report and let the user decide.

## Output back to the user

When the loop ends, surface:

- PASS / FAIL / BLOCKED status with the run-id
- Iteration count used
- Files changed (from `git diff --name-only <base_ref>`)
- Verified coverage percentage (from the evidence gate, not the tester's claim)
- Pointer to `.dev-squad/runs/<run-id>/review.md` for full detail

Keep this terminal output under 200 words. The detail is on disk.

### Wiki offer (after PASS or BLOCKED)

After printing the closing report, ask the user one follow-up question:

> Ingest this run into the wiki? `design.md` would feed `subsystems/<inferred>.md`, `review.md` would update `lessons/*` for any recurring issues found, `BLOCKED.md` (if present) would mandate a `lessons/<slug>.md` entry. — yes / no / preview

- **yes** → dispatch `/wiki-ingest --latest-run`.
- **preview** → show the proposed ingest plan (which raw files, which wiki destinations) without writing anything; then re-ask yes / no.
- **no** → do nothing.

Never auto-ingest. The user owns the wiki write boundary.

## Token discipline at the orchestrator level

- Don't re-read state.json on every transition — read once at start, hold the structure in working memory, write back on each transition.
- Evidence-gate re-runs reuse the exact commands the agents recorded; send output to disk and read only exit codes and the coverage report file — never paste full logs into context.
- Don't pass full file contents to subagents. Pass file paths and let the subagent Read what it needs.
- Don't paste subagent output into your own response back to the user — summarize from the artifact files instead.

## Resuming an interrupted loop

If `.dev-squad/state.json` exists and `current_state` is not `COMPLETE` or `BLOCKED` when the orchestrator starts:

1. Ask the user: "An in-progress run exists for `<task>` (iteration <N>, last state <STATE>). Resume, restart, or start a new task?"
2. On Resume: pick up at the state recorded in state.json.
3. On Restart: archive the old run dir to `.dev-squad/runs/<run-id>-abandoned-<timestamp>/` and start fresh.
4. On New task: start fresh with a new run-id.
