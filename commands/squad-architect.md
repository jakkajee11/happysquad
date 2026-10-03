---
description: Run only the architecter agent — produce a design document for a task and stop. Does not advance to implementation.
argument-hint: <task description>
---

`HS="${CLAUDE_PLUGIN_ROOT}/bin/hs"`

1. If `$ARGUMENTS` is empty, ask the user for the task with AskUserQuestion.
2. Run `$HS run start "<task>"`. Parse the JSON line — it returns the ARCHITECT `dispatch` action.
3. Act on it exactly as `${CLAUDE_PLUGIN_ROOT}/skills/squad-loop/SKILL.md`'s protocol says: read
   `prompt_file`, call the Agent tool once with `subagent_type: happysquad:hs-architecter`,
   `model: <model>`, prompt = the file's content verbatim.
4. When the agent returns, run `$HS advance`.
5. Stop. Print the design path `.happysquad/runs/<run-id>/design.md` and tell the user to resume
   with `/squad-resume`. The run stays in progress by design — this command does not advance past
   ARCHITECT.
