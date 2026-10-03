---
description: Resume the current happysquad run from exactly where the hs engine left it.
---

`HS="${CLAUDE_PLUGIN_ROOT}/bin/hs"`

Load `${CLAUDE_PLUGIN_ROOT}/skills/squad-loop/SKILL.md`.

Run `$HS resume`. If it prints `{"action": "error", "message": "no current run"}`, tell the user
there is nothing to resume and stop. Otherwise continue the skill's protocol from the returned
action (step 2) — a `done` action for a BLOCKED or COMPLETE run is reported, not re-dispatched.
