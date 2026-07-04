---
name: brainstorm-session
description: |
  Runs a structured 3-round brainstorm where the happysquad's five agents (product, architecter,
  implementer, tester, reviewer) analyze a new requirement or problem together and converge on a
  consensus solution. Round 1 is divergent POV in parallel, round 2 is cross-review in parallel,
  round 3 is single-author synthesis plus per-agent sign-off. Trigger when the user runs
  /brainstorm, asks to "have the squad discuss", "let the agents brainstorm", "find the best
  approach together", "explore options before implementing", or any time a fresh requirement
  needs analysis before the dev-loop starts.
---

# Brainstorm Session

A 3-round structured discussion that turns a fresh requirement into a consensus solution the dev-loop can execute against. Designed to front-load disagreement and surface trade-offs *before* the architecter commits to a design, so the loop has fewer rework cycles.

## When to use this vs /happysquad-loop

| Situation                                                                   | Use this        |
|-----------------------------------------------------------------------------|-----------------|
| Brand-new requirement, multiple plausible approaches, unclear scope         | /brainstorm     |
| Requirement is well-scoped and the path is obvious                          | /happysquad-loop |
| Existing design failed review — design itself looks wrong                   | /brainstorm     |
| Existing design failed review — implementation bug                          | /happysquad-loop |
| Stakeholder gave a vague ask, e.g. "let users export their data"            | /brainstorm     |

A brainstorm typically costs more tokens than skipping straight to architect, but saves rounds when the problem space is genuinely ambiguous. When in doubt, the architecter can run alone and the user can escalate to brainstorm if the round-1 design feels off.

## The five voices

Each agent in the brainstorm has a fixed perspective. Do not let them drift out of role.

| Agent       | Question they answer                                            | Failure mode if absent     |
|-------------|------------------------------------------------------------------|----------------------------|
| product     | What does the customer actually need? What is success?           | Over-engineered solutions  |
| architecter | How does this fit our system? What's the right shape?            | Implementation drift       |
| implementer | How hard is this to build? What breaks? What's the dev exp?      | Unbuildable designs        |
| tester      | How do we know it works? What's hard to verify?                  | Unverifiable success       |
| reviewer    | What goes wrong in production? Where's the risk surface?         | Shipping foot-guns         |

## File layout the session produces

```
.happysquad/brainstorms/<session-id>/
├── topic.md                  # the input requirement, copied verbatim
├── session.json              # metadata + state
├── round1-product.md
├── round1-architecter.md
├── round1-implementer.md
├── round1-tester.md
├── round1-reviewer.md
├── round2-product.md
├── round2-architecter.md
├── round2-implementer.md
├── round2-tester.md
├── round2-reviewer.md
├── consensus.md              # synthesis from round 3 (architecter authors)
└── signoffs.md               # aggregated APPROVE / DISSENT from each agent
```

`session-id` format: `YYYYMMDD-HHMMSS-bs-<6-word-slug>`.

## session.json

```json
{
  "session_id": "20260520-114500-bs-export-user-data",
  "topic": "<one-line topic>",
  "current_round": 3,
  "status": "in_progress",
  "rounds": {
    "1": { "completed_at": "...", "agents_completed": ["product", "architecter", "..."] },
    "2": { "completed_at": "...", "agents_completed": [...] },
    "3": { "consensus_author": "architecter", "signoffs": { "product": "APPROVE", "implementer": "DISSENT", "tester": "APPROVE", "reviewer": "APPROVE" } }
  },
  "started_at": "...",
  "updated_at": "..."
}
```

## Orchestration protocol

### Setup

1. If `<topic>` is empty, ask the user with AskUserQuestion. Do not invent a topic.
2. **Stack profile check** — same as squad-loop: if `.happysquad/stack-profile.md` is missing, invoke `stack-detector` first ("First run in this project — scanning stack"). If present but a manifest is newer than the profile, offer to refresh. The brainstorm's 5 agents will receive their per-agent skill list from `stack-profile.json` when dispatched.
3. **Project conventions check (CLAUDE.md)** — same as squad-loop: if no `CLAUDE.md` exists at the repo root or `.claude/CLAUDE.md` and `.happysquad/.claude-md-nudged` is absent, nudge the user once (generate via /init / don't-ask-again / ask-next-time, recording the choice in the marker). Advisory — never blocks the session.
4. Generate session-id.
5. Create `.happysquad/brainstorms/<session-id>/`.
6. Write `topic.md` containing the verbatim topic plus any attached context the user provided.
7. Initialize `session.json` with `current_round = 1`, `status = in_progress`.

### Round 1 — Divergent POV (parallel)

Dispatch all five agents **in parallel** using a single message with five Agent tool calls. Each gets:
- the topic.md path
- the session-id
- the instruction "round 1 — write your independent perspective only, do not read other agents' work"

Each agent writes `round1-<agent>.md` and ends with their R1 completion marker.

Wait for all five markers before moving on. Update session.json.

### Round 2 — Cross-review (parallel)

Dispatch all five agents **in parallel** again. Each gets:
- all five round-1 file paths
- the instruction "round 2 — read the other four round-1 notes; respond with where you agree, where you disagree, what new questions arise, what changed in your position"

Each agent writes `round2-<agent>.md`. Wait for all markers.

### Round 3 — Synthesis + sign-off (sequential)

Round 3 is sequential because the consensus must exist before sign-off:

1. Dispatch **architecter** alone with the instruction "round 3 synthesis — read all 10 round-1 and round-2 files; write `consensus.md` with: (a) the agreed solution at a strategic level, (b) trade-offs the squad considered, (c) dissenting positions captured fairly, (d) open questions for the user". Architecter ends with `CONSENSUS_READY: <path>`.

2. Dispatch the other four agents (**product, implementer, tester, reviewer**) **in parallel** with the consensus path and the instruction "round 3 sign-off — read consensus.md, write `signoff-<agent>.md` with exactly APPROVE or DISSENT plus one paragraph".

3. Aggregate the four signoffs plus the architecter's implicit approval (as consensus author) into `signoffs.md`:

```markdown
# Sign-offs — session <session-id>

| Agent       | Verdict | Reason                                              |
|-------------|---------|-----------------------------------------------------|
| product     | APPROVE | …                                                   |
| architecter | AUTHOR  | (wrote the consensus)                               |
| implementer | DISSENT | …                                                   |
| tester      | APPROVE | …                                                   |
| reviewer    | APPROVE | …                                                   |

## Convergence
<one of: full-consensus | minor-dissent | major-dissent>
```

### Convergence rules

- **full-consensus** = 4 of 4 sign-offs APPROVE → recommend proceeding to /happysquad-loop.
- **minor-dissent** = 1 of 4 dissents and the dissenter's blocking condition is small (their own paragraph names a "smallest change that would flip me to APPROVE") → present the dissent to the user with the suggested fix; offer to amend consensus and re-sign or proceed anyway.
- **major-dissent** = 2 or more dissents, OR a dissent whose blocking condition is fundamental → surface the disagreement to the user with the dissenting paragraphs verbatim; suggest a 4th round only if the user requests it; otherwise stop.

Never re-loop silently. The user decides whether to add a round.

## After the session

Status set to `complete`. Report back to the user with:

- session-id and final convergence state
- a 5-line summary of the consensus
- the dissenting positions verbatim (if any)
- pointer to `consensus.md`
- the question: **"Proceed to /happysquad-loop with this consensus as the task input?"**

Always ask. Never auto-pipe — the user opted into "ถามผู้ใช้ก่อน".

If the user says yes, hand off `consensus.md` to /happysquad-loop as the task description (specifically, the orchestrator pre-fills `task` with a one-paragraph distillation from consensus.md + attaches the full file as design input that the architecter will read first thing).

### Wiki offer (after consensus is written)

After surfacing the consensus summary and *before* the "proceed to /happysquad-loop?" question, ask one follow-up:

> Ingest this consensus into the wiki as a Decision? `consensus.md` would become `decisions/<slug>.md`, with dissenting sign-offs becoming the Alternatives Considered section. — yes / no / preview

- **yes** → dispatch `/wiki-ingest --latest-brainstorm`.
- **preview** → show the proposed ingest plan without writing anything; then re-ask yes / no.
- **no** → do nothing.

A brainstorm consensus is the squad's ADR — capturing it in the wiki is high-value because future brainstorms will read `decisions/*` before re-debating the same trade-offs. Encourage but don't force.

## Parallel dispatch is mandatory

Rounds 1 and 2 must be dispatched in a single message with multiple Agent tool calls. Sequential dispatch in those rounds is a bug — it wastes wall-clock time and provides no benefit (the agents are not supposed to see each other's work mid-round anyway).

Round 3 sign-offs are also parallel, after the consensus exists.

## Token discipline

- Per round, each agent produces 200-500 words. A full 3-round session is ~5000-8000 tokens of output spread across 5 agents — cheaper than one monolithic deep-analysis pass on opus.
- Agents receive file paths, not file contents. They Read what they need.
- The orchestrator does not paste round outputs back into its messages to the user. It summarizes from `consensus.md` only.
- If the topic is small enough that you suspect round 2 won't add anything, the user can pass `--rounds=2` to skip cross-review — but default is 3 and you should not silently drop rounds.

## Dissent vs disagreement

Disagreement *during* rounds 1-2 is the point. Multiple agents flagging a trade-off is healthy.

DISSENT *at sign-off* is a veto. It blocks the consensus from being declared converged. Treat it that way — don't paper over dissent in the summary you give the user.

## Resuming an interrupted session

If `session.json` exists and `status = in_progress`:

1. Ask the user: "Brainstorm session `<topic>` is at round <N>. Resume, restart, or start a new topic?"
2. Resume: continue from `current_round`, re-dispatching only the agents whose round-N file is missing.
3. Restart: archive to `<session-id>-abandoned-<timestamp>/` and start fresh.

## Standalone product-critique mode

`/brainstorm --quick` skips to a single product-agent critique without the full 3-round session. Useful when the question is purely "is this requirement clear enough to start" rather than "what's the best solution". Product agent writes a critique and the orchestrator reports back; no other agents are dispatched.
