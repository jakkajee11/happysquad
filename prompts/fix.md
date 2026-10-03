You are the **{{agent}}** in fix mode. Run `{{run_id}}`, iteration {{iteration}}, inner pass {{inner_pass}}.

## Task
{{task}}

## What to fix
Read `{{feedback_path}}` first. Every blocker row has a `verify` command; the engine will run each one after you finish, and a fix that fails its own check comes straight back to you. Fix exactly those findings. Do not widen scope.

## Inputs
- Design: `{{design_path}}`
- Build command: `{{build_cmd}}` · Test command: `{{test_cmd}}`
- Files you may create or modify (nothing else):
{{owned_files}}

## Output — both required
1. The fixes in the repo. Run the build (implementer) or the affected tests (tester) yourself before finishing.
2. `{{out_file}}` — JSON exactly in this shape:

```json
{{out_schema}}
```

Implementer: `files` = every file you changed this pass. Tester: `new_tests` = test files created this pass only (already-proven files are not re-proven); if you created any, produce `{{phase_dir}}/redgreen.json` with `{{hs}} redgreen --ref {{proof_ref}} --tests <files>`.

## Rules
- Fix the finding, not the check: a `grep`-based verify passes just as well with a real fix.
- If you disagree with a finding, say so in the artifact and leave the code; the engine reports it as unresolved.
- Do not commit, branch, stash, or push.

## Finish
Run `{{hs}} validate {{out_file}}` and fix any errors.

Then stop: end your turn with a one-line summary. Do not wait for anything, do not schedule a follow-up, do not journal to PROGRESS.md.
