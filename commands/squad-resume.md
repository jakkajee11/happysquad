---
description: Resume the most recent in-progress happysquad work — scans all state files, finds the latest run/brainstorm/fleet that isn't finished, and continues from exactly where it left off.
---

Find and continue in-progress happysquad work. State survives across sessions because it lives in `.happysquad/` inside the repo, so this command works after closing and reopening a session.

Steps:

1. Scan for state across all three modes:
   - `.happysquad/state.json` — dev-loop runs. In-progress = `current_state` is not `COMPLETE` and not `BLOCKED`.
   - `.happysquad/brainstorms/*/session.json` — brainstorm sessions. In-progress = `status == "in_progress"`.
   - `.happysquad/fleets/*/fleet.json` — fleet runs. In-progress = `status == "in_progress"`.
2. Build a candidate list. For each candidate capture: kind (dev-loop / brainstorm / fleet), task or topic, current position (state / round / running-count), and `updated_at`.
3. Branch on the count:
   - **Zero candidates** → tell the user: "No in-progress happysquad work found. Start with /happysquad-loop, /brainstorm, or /squad-fleet." Stop.
   - **Exactly one** → resume it directly (step 4).
   - **More than one** → use AskUserQuestion to let the user pick which to resume. Show each candidate's kind, task/topic, position, and how long ago it was updated. Default-highlight the most recently updated.
4. Resume the chosen candidate by loading the right skill and entering its resume protocol:
   - **dev-loop** → load `${CLAUDE_PLUGIN_ROOT}/skills/squad-loop/SKILL.md`. Read `state.json`, announce "Resuming run `<run-id>` at state `<current_state>`, iteration `<N>` of `<cap>`", then continue the state machine from `current_state`. For parallel runs, re-check which workstreams are pending vs complete and only dispatch the pending ones.
   - **brainstorm** → load `${CLAUDE_PLUGIN_ROOT}/skills/brainstorm-session/SKILL.md`. Resume at `current_round`, re-dispatching only the agents whose round-N file is missing.
   - **fleet** → load `${CLAUDE_PLUGIN_ROOT}/skills/fleet-orchestrator/SKILL.md`. Dispatch the next pending children up to `max_parallel`; children that were mid-run resume from their own worktree `state.json`.
5. Before doing any work, show a 5-line recap of where things stand so the user can confirm this is the right thing to resume. If the user objects, offer to switch to a different candidate or to `/squad-status` for the full picture.

Notes:
- This command never starts new work — it only continues existing state. To start fresh, use the mode-specific command.
- If a candidate is `BLOCKED`, do not auto-resume it — surface it and point the user at its `BLOCKED.md`. A BLOCKED run needs a human decision, not a silent retry.
- If a manifest changed since the stack profile was generated (compare mtimes), mention it and offer `/squad-detect` before resuming a dev-loop.
