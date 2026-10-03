---
name: squad-loop
description: |
  Drives the happysquad dev loop (architect → implement → test → conflict gate → risk → specialists →
  review) through `bin/hs`, which owns every state transition, gate and verdict. Trigger on
  /happysquad-loop, /squad-resume, or "run the squad".
---

# Squad loop driver

`hs` owns the run. You only relay actions: run a command, read one JSON line, do what it says.

```
HS="${CLAUDE_PLUGIN_ROOT}/bin/hs"
```

## Protocol

1. **Start.** `$HS run start "<task>"` (add `--lite`, `--no-parallel`, `--driver agent-tool` as the
   caller needs). If told to resume: `$HS resume`. Parse the single JSON line it prints.
2. **Act on `action`:**
   - `dispatch` → Read `prompt_file`. Call the Agent tool once: `subagent_type: happysquad:hs-<agent>`
     (e.g. `happysquad:hs-implementer`), `model: <model>`, prompt = the file's content verbatim. When
     the agent returns, run `$HS advance`.
   - `dispatch_many` → same, every entry in **one** message with multiple Agent calls, then `$HS
     advance`. `agent: specialist` → `subagent_type: happysquad:hs-specialist`.
   - `wait` → run `$HS wait --timeout 540` (Bash tool, `timeout: 600000`). Prints the next action when
     the files land, or `wait` again with `timed_out: true` — rerun it. If its `dispatches` lists an
     agent whose Agent-tool call already errored, re-send that entry once.
   - `advance` → `$HS advance`.
   - `ask` → AskUserQuestion with the given options, then `$HS answer <key> <value>`, then `$HS next`.
   - `done` → report in ≤150 words: status, run_id, iterations, files_changed, coverage, report path,
     suggested_commit (or blocked_md + cause). Stop.
   - `error` → report the message. Stop.
3. **Loop** back to step 2 with the new JSON line.

## Resume

`$HS resume` recovers a run whose driver stopped: disk outputs are consumed, live agents are waited
on, quiet ones are re-dispatched. Use it instead of `run start` for a run already in progress.

## Lite

Pass `--lite` for small tasks, or leave it — `hs` auto-selects lite for size-S work.

## Failure handling

- Agent tool error or empty return → `$HS next` (re-waits on the same `dispatches`), re-send that
  entry once; second failure → `$HS block "agent error: <summary>" --cause agent`, report, stop.
- A command prints nothing or non-JSON → retry once; still broken → report the raw output, stop.

## Rules

- One `hs` command per step. Never guess the next phase; read it from the JSON.
- Never read design.md, review.md, gates files, or state files yourself. Never edit `.happysquad/`.
- Never run the build or tests yourself. Never touch git.
- Never end your turn while the last action was `dispatch`, `dispatch_many`, `wait` or `advance`.
- Do not paste agent output or file contents into your messages.
