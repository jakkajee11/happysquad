---
description: Run a 3-round structured brainstorm where five agents (product, architecter, implementer, tester, reviewer) analyze a topic together and converge on a consensus solution. Asks before piping to /happysquad-loop.
argument-hint: <topic — a requirement, problem, or proposed feature>
---

Load the `brainstorm-session` skill at `${CLAUDE_PLUGIN_ROOT}/skills/brainstorm-session/SKILL.md` and follow it exactly.

Steps:

1. If `$ARGUMENTS` is empty, ask the user with AskUserQuestion for the topic. Do not invent one.
2. If `$ARGUMENTS` contains `--quick`, jump to the standalone product-critique path described at the bottom of the skill (single product agent, no rounds).
3. If `$ARGUMENTS` contains `--rounds=2`, skip round 2 (cross-review) and go from round 1 directly to synthesis. Note this in `session.json`. Default behavior is 3 rounds.
4. Otherwise check for an in-progress session in `.happysquad/brainstorms/*/session.json` — if found, follow the resume protocol.
5. Generate a new session-id, create the brainstorm directory, write `topic.md`, initialize `session.json`.
6. **Round 1 (parallel)** — Dispatch all five agents (product, architecter, implementer, tester, reviewer) in a single message with five Agent tool calls. Each receives the topic path, session-id, round number, and the round-1 instruction. Use the model from `.happysquad/config.json` (defaults: opus for product/architecter/reviewer, sonnet for implementer/tester). Wait for all five R1 markers.
7. **Round 2 (parallel)** — Dispatch all five agents again with the round-2 instruction and paths to all five round-1 files. Wait for all five R2 markers. (Skip this if `--rounds=2` was passed.)
8. **Round 3 synthesis (sequential)** — Dispatch the architecter alone to write `consensus.md`. Wait for `CONSENSUS_READY: <path>`.
9. **Round 3 sign-off (parallel)** — Dispatch product, implementer, tester, reviewer in parallel with the consensus path. Wait for all four sign-off markers.
10. Aggregate sign-offs into `signoffs.md` with the convergence verdict (full-consensus / minor-dissent / major-dissent) per the skill's rules.
11. Update session.json to `status = complete`.
12. Report back to the user:
    - Session ID + convergence state
    - 5-line summary of the consensus
    - Any DISSENT paragraphs verbatim
    - Pointer to `consensus.md`
    - The question: **"Proceed to /happysquad-loop with this consensus as the task input?"**
13. If the user says yes, invoke /happysquad-loop with a one-paragraph distillation of consensus.md as the task, and ensure the orchestrator passes the full consensus path to the architecter so it reads the consensus before designing.

Never auto-pipe to /happysquad-loop. Always ask.

Never silently re-loop past round 3. If convergence is major-dissent, surface it and stop — let the user decide whether to add a 4th round, escalate, or proceed anyway.
