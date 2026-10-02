---
name: hs-loop
description: |
  v1 engine driver (P0 spike). Drives the happysquad dev loop through `bin/hs`, which owns every
  state transition, gate and verdict. Trigger on /hs-loop. Do not use for the 0.16 /happysquad-loop.
---

# hs loop driver

`hs` owns the run. You only relay actions: run a command, read one JSON line, do what it says.

```
HS="${CLAUDE_PLUGIN_ROOT}/bin/hs"
```

## Protocol

1. **Start.** `$HS run start "<task>"` (add `--lite` if asked). If told to resume: `$HS resume`. Parse the single JSON line it prints.
2. **Act on `action`:**
   - `dispatch` → Read `prompt_file`. Call the Agent tool once: `subagent_type: happysquad:<agent>`, `model: <model>`, prompt = the file's content verbatim. When the agent returns, run `$HS advance`.
   - `dispatch_many` → same, every entry in **one** message with multiple Agent calls, then `$HS advance`.
   - `wait` → run `$HS wait --timeout 540` with the Bash tool (`timeout: 600000`). It prints the next action when the awaited files land, or `wait` again with `timed_out: true` — then run it again.
   - `advance` → `$HS advance`.
   - `ask` → AskUserQuestion with the given options, then `$HS answer <key> <value>`, then `$HS next`.
   - `done` → report in ≤150 words: status, run_id, iterations, files_changed, coverage, report path, suggested_commit (or blocked_md + cause). Stop.
   - `error` → report the message. Stop.
3. **Loop** back to step 2 with the new JSON line.

## Failure handling

- Agent tool error or empty return → `$HS next` (re-renders the same dispatch) and retry once. Second failure → `$HS block "agent error: <summary>" --cause agent`, report, stop.
- A command printing nothing or non-JSON → run it once more; if still broken, report the raw output and stop.

## Rules

- One `hs` command per step. Never guess the next phase; always read it from the JSON.
- Never read design.md, review.md, gates files, or state.json yourself. Never edit anything under `.happysquad/`.
- Never run the build or tests yourself. Never touch git.
- Never end your turn while the last action was `dispatch`, `dispatch_many`, `wait` or `advance`.
- Do not paste agent output or file contents into your messages.
