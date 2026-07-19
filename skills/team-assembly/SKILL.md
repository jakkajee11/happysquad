---
name: team-assembly
description: |
  Analyzes a spec or requirement and produces a recommended team composition — squad review mode,
  per-agent model assignments, specialist reviewer toggles, and limited external-executor roles —
  before implementation starts. Writes an approval-gated `.happysquad/team-plan.json` +
  `team-plan.md`. Triggers: /squad-assemble, "assemble the team", "plan the team", "recommend team
  composition", "who should work on this", "team plan before the loop", "assign models for this
  task". Run before /happysquad-loop on non-trivial work; squad-loop behaves exactly as before when
  no approved plan exists.
---

# Team Assembly

Reads a spec/requirement, sizes it, and decides how the squad should staff the task: which review
mode to run, which models each agent should use, which specialist reviewers to force on or off, and
whether limited external-executor roles (`glm` / `opencode`) are worth enabling. The output is a
**team plan** that requires explicit user approval before squad-loop will honor it.

## Why this exists

happysquad Claude agents are the primary team for every task, full stop. `glm` / `opencode` (both
hit the same Z.ai GLM backend) exist only to offload work Claude agents don't need to do personally:
cheap mechanical edits, advisory cross-review, and quota fallback — never as parallel
co-implementers. Left to defaults, every task gets the same review mode and model mix regardless of
size or risk, and nobody decides up front whether external offload is worth the latency. This skill
makes that call once, with the user's sign-off, before real work starts — instead of the loop
guessing mid-run.

## Where the plan lives

```
.happysquad/team-plan.json     # canonical, machine-consumed by squad-loop
.happysquad/team-plan.md       # human-readable, rationale per choice
```

Both are written together. JSON is authoritative; markdown is what the user reads before approving.

## Procedure

1. **Resolve spec input.** `$ARGUMENTS` is either a file path (Read it) or inline requirement text
   (use as-is). If empty, ask via AskUserQuestion. Never invent a spec.
2. **Stack-profile dependency.** If `.happysquad/stack-profile.json` doesn't exist, invoke
   `stack-detector` first, then read the resulting profile. It feeds the mechanical-share estimate —
   a scaffolding-heavy stack skews toward more boilerplate.
3. **Existing plan check.** If `.happysquad/team-plan.json` already exists, ask overwrite / keep.
   On overwrite, archive the old file to `.happysquad/team-plan-<timestamp>.json` first.
4. **Analyze the spec:**
   - Size — S/M/L by acceptance-criteria count, estimated file count, whether it introduces a new
     subsystem.
   - Workstream estimate — how many independent slices the architecter would likely produce.
   - Security/performance surface — reuse squad-loop §9's risk-pattern keywords against the spec
     text (auth, payment, secrets, migration, query, loop, external API, cache, etc.).
   - Mechanical-work share — how much of the task reads as renames/boilerplate/scaffolding/docs
     versus real design work.
5. **External availability.** Check `command -v glm` and `command -v opencode`. This is the only
   permitted interaction with external executors at this stage — never invoke them for real work
   while assembling the plan.
6. **Apply the decision rules** below to set `review_mode`, `specialists`, `models`,
   `config_overrides`, and `external_executors.roles`.
7. **Write** `.happysquad/team-plan.json` (canonical, `"approved": false`), then
   `.happysquad/team-plan.md` (rationale per choice, human-readable).
8. **Approval gate.** Present a ≤15-line summary, then AskUserQuestion with Approve / Edit / Reject.
   - Approve → set `"approved": true` + `"approved_at"`, done.
   - Edit → walk the fields the user wants changed one at a time, re-ask until approved or rejected.
   - Reject → leave `"approved": false`; the file stays on disk as a record but squad-loop ignores it.

## Decision rules

| Signal | Rule |
|---|---|
| Size S | `review_mode: single`, cap 3 |
| Size M | `review_mode: split-on-risk` |
| Size L | `review_mode: split` + recommend `/brainstorm` before looping |
| High mechanical share | enable `external_executors.roles.mechanical_tasks` |
| Auth/payment surface detected | `specialists.security-reviewer: always` + enable `cross_review` |
| Docs-only task | downgrade `models.implementer` to a lighter model |

**Hard rule — do not soften:** happysquad Claude agents are the primary team. `glm` / `opencode` are
limited to exactly three roles — mechanical work, advisory cross-review, quota fallback — and are
never parallel co-implementers.

## External executors

Canonical invocation: `glm -p "<prompt>" --permission-mode acceptEdits --allowedTools "..."`.
Alternate: `opencode run` — same Z.ai backend, never invoke both for the same role. One glm
round-trip takes roughly 30s minimum; factor that into whether a role is worth enabling for a small
task.

This skill only **plans** whether external executors are enabled and for which roles — it never
shells out to them beyond the `command -v` check, and it never manages tmux. Actual invocation,
timeouts, and pane visibility belong to squad-loop §11; external execution is surfaced to the user
in visible tmux panes by the loop, not by this skill.

## Schema — team-plan.json

```json
{
  "generated_at": "…", "skill_version": "0.1",
  "spec_source": "docs/spec.md | inline", "task_summary": "<one line>",
  "approved": false, "approved_at": null,
  "analysis": { "size": "S|M|L", "est_workstreams": 2,
    "security_surface": "none|low|high", "performance_surface": "none|low|high",
    "mechanical_share": "none|low|high" },
  "pre_loop": { "recommend_brainstorm": false, "reason": "…" },
  "review_mode": "single|split|split-on-risk",
  "specialists": { "security-reviewer": "auto|always|off", "performance-reviewer": "auto|always|off",
    "requirement-reviewer": "auto|always|off", "standard-reviewer": "auto|always|off" },
  "models": { "architecter": "opus", "implementer": "sonnet", "tester": "sonnet", "reviewer": "opus" },
  "config_overrides": { "cap": 5, "coverage_threshold": 80 },
  "external_executors": {
    "enabled": true,
    "primary": { "name": "glm", "invoke": "glm -p", "alternate": "opencode run", "availability": "path-verified" },
    "roles": {
      "mechanical_tasks": { "enabled": true, "categories": ["boilerplate","rename","formatting","docs"] },
      "cross_review": { "enabled": true, "scope": "full-diff", "advisory_only": true },
      "quota_fallback": { "enabled": true, "retry_threshold": 2, "allowed_phases": ["implement","test"] }
    }
  },
  "rationale": { "review_mode": "…", "models": "…", "specialists": "…", "external_executors": "…" }
}
```

Schema constraints — never violate these when writing the plan:
- `external_executors.roles.cross_review.advisory_only` is fixed `true`. Never write `false`.
- `external_executors.roles.quota_fallback.allowed_phases` may only contain `"implement"` and/or
  `"test"` — never `"review"`. The chief reviewer's verdict is never delegated.
- Agent name is spelled **architecter** throughout — not "architect".

## What this skill must NOT do

- Never self-approve. The approval gate always requires an explicit user answer.
- Never edit `.happysquad/config.json` or any project source file — this skill only writes plan
  files.
- Never invoke `glm` or `opencode` for real work — `command -v` availability checks only.
- Never enable external executors for anything outside the three roles above.
- Never embed tmux commands or pane mechanics — that belongs to squad-loop §11, not this skill.

## Token discipline

Target under 25 tool calls total. Reuse an existing stack-profile instead of re-scanning. Don't
re-read a file already read earlier in the same run.

## Completion signal

When the plan is written and the approval gate has resolved, your final message must include:

```
TEAM_PLAN_READY: .happysquad/team-plan.json approved=<true|false>
```
