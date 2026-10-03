---
description: Show the happysquad's current run state via the hs engine.
---

`HS="${CLAUDE_PLUGIN_ROOT}/bin/hs"`

1. Run `$HS status`. If it prints `{"runs": 0}`, tell the user "No happysquad run on record. Start
   with /happysquad-loop." Stop.
2. Present its JSON as at most 15 lines: `run_id`, `state`, `iteration`/`cap`, `mode`, `lite`,
   workstreams (name: impl/test), `pending` (phase/ws/axis), `gates`, `task`, `block_cause`,
   `updated_at`.
3. Add one "next command" line:
   - `state` not `COMPLETE`/`BLOCKED` → "Resume with `/squad-resume`."
   - `state` is `COMPLETE` → nothing further.
   - `state` is `BLOCKED` → "Read `.happysquad/runs/<run_id>/BLOCKED.md`, then `/squad-resume`."
