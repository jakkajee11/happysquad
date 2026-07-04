---
description: Run the full dev-squad loop (architect → implement → test → conflict-gate → review) on a task, iterating until pass or the round cap. Auto-detects parallel workstreams from the architecter's design and dispatches implementer/tester in parallel waves when safe.
argument-hint: <task description> [--no-parallel] [--worktree]
---

Load the `squad-loop` skill, then drive the full hand-off loop for the task described in `$ARGUMENTS`.

Concretely:

1. Read `${CLAUDE_PLUGIN_ROOT}/skills/squad-loop/SKILL.md` — that is the authoritative state machine and contract. Follow it exactly.
2. If `$ARGUMENTS` is empty (after stripping flags), ask the user for the task with AskUserQuestion. Do not invent a task.
3. Parse flags from `$ARGUMENTS`:
   - `--no-parallel` → force `mode=single` even if the architecter's design has multiple workstreams. Useful for cautious first runs on a new codebase.
   - `--worktree` → set `parallel_isolation=always-worktree` for this run, regardless of `.dev-squad/config.json` default.
4. Run setup per the skill's "Setup" section: check stack-profile, check for CLAUDE.md (nudge once if missing), generate run-id, create run directory, initialize state.json.
5. If `.dev-squad/state.json` shows an in-progress run that is not COMPLETE/BLOCKED, follow the "Resuming an interrupted loop" protocol.
6. Step through the state machine. After ARCHITECT, parse the marker `DESIGN_READY: … workstreams=N parallel=<bool>`:
   - If `parallel=true` AND `--no-parallel` was not passed → enter `PARALLEL_IMPLEMENT`. Build the DAG, dispatch wave-by-wave in single multi-Agent-tool messages.
   - Otherwise → enter linear `IMPLEMENT`.
7. After each implementation phase, run the evidence gate per the skill's "Evidence gate" section (re-run the implementer's recorded build commands; on mismatch → feedback + re-dispatch), then run the corresponding TEST phase (parallel or single, same shape), then its evidence gate (re-run the test commands, read coverage from the coverage tool's report file, confirm the `## Red→green evidence` section exists).
8. Run `CONFLICT_GATE` (no-op for single-workstream runs; full check for parallel).
9. Dispatch `reviewer`. Honor its `next` field per the routing rules — for parallel runs, also honor `workstreams=<list>` for subset re-dispatch. On a FAIL routed to implementer/tester where every blocker has a machine-checkable `Verify` command, take the inner fix loop per the skill's "Inner fix loop" section (fix → run per-finding Verify checks → evidence gate → delta review) instead of a full pipeline round.
10. Run the skill's convergence check on every FAIL before routing (Recurrence column: second repeat → escalate route to architecter; repeat after redesign or two zero-progress rounds → early BLOCKED).
11. Stop on COMPLETE, BLOCKED (cap or convergence), or when iteration > cap. Never silently retry past the cap.

After the loop ends, surface the wiki ingest offer per the skill's "Wiki offer" section. Keep the closing report under 200 words.
