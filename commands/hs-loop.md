---
description: (v1 P0 spike) Run the hs-engine dev loop — architect → implement → test → review — with every gate and transition computed by bin/hs. The 0.16 loop remains /happysquad-loop.
argument-hint: <task description> [--lite]
---

Load `${CLAUDE_PLUGIN_ROOT}/skills/hs-loop/SKILL.md` and drive the loop for the task in `$ARGUMENTS` exactly as the skill's protocol says.

If `$ARGUMENTS` is empty, ask the user for the task with AskUserQuestion. Strip a trailing `--lite` flag and pass it to `hs run start`.
