---
description: Analyze a spec/requirement and produce a recommended team composition (review mode, models, specialists, limited external-executor roles) gated behind explicit approval. Run before /happysquad-loop on non-trivial work.
argument-hint: <spec file path or requirement text>
---

Load the `team-assembly` skill at `${CLAUDE_PLUGIN_ROOT}/skills/team-assembly/SKILL.md` and run the full procedure.

Steps:

1. Resolve the spec: if `$ARGUMENTS` is a file path, Read it; otherwise treat `$ARGUMENTS` as the requirement text directly. If `$ARGUMENTS` is empty, ask the user for the spec — never invent one.
2. Check for `.happysquad/stack-profile.json`. If absent, invoke `stack-detector` first (Skill call or `/squad-detect`) and read the profile it writes.
3. Check for an existing `.happysquad/team-plan.json`. If present, ask overwrite / keep. If overwriting, archive the old file to `.happysquad/team-plan-<timestamp>.json` first.
4. Analyze per the skill: size (S/M/L), workstream estimate, security/performance surface (reuse squad-loop §9 risk keywords against the spec text), mechanical-work share.
5. Check external availability: `command -v glm`, `command -v opencode`. No other interaction with external executors at this stage — never invoke them for real work.
6. Apply the skill's decision-rules table to set `review_mode`, `specialists`, `models`, `config_overrides`, `external_executors.roles`.
7. Write `.happysquad/team-plan.json` (canonical, `approved: false`), then `.happysquad/team-plan.md` (rationale per choice).
8. Present a ≤15-line summary and run the approval gate via AskUserQuestion: Approve / Edit / Reject.
   - Approve → set `approved: true` + `approved_at`.
   - Edit → walk fields one at a time, re-ask until approved or rejected.
   - Reject → leave `approved: false`.
9. Report the completion signal `TEAM_PLAN_READY: .happysquad/team-plan.json approved=<true|false>` and suggest `/happysquad-loop` as the next command.

Use Read/Glob/Grep/Write/Edit/Bash (`command -v` only) — never invoke `glm`/`opencode` for actual work from this command.
