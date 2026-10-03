# seeded-bugs fixture (spec §18.2 / §1.2)

A self-contained recall fixture: a copy of `hs/` with three plausible-looking defects
planted in it, used to measure whether a reviewer prompt (0.16.2 or v1.0) catches them.

Rebuild with `python3 evals/fixtures/seeded-bugs/make.py` (idempotent — always rebuilds
`hs/` fresh from the current main `hs/` and re-applies the same three edits). Commit the
resulting `hs/` and `diff.patch`; they are the fixture, not build output.

## Planted bugs

| bug | file:line (fixture copy) | mechanism |
|-----|---------------------------|-----------|
| B-A | `hs/machine.py:102` | `_same_ref(a, b)` returns `True` for any two non-empty strings — dropped the prefix check and the `>= 7` length guard. |
| B-B | `hs/gates.py:113` | `gate_test` recomputes `tests_ok` from only the config-sourced command results, so a failing agent-supplied `test_cmds` entry no longer fails the gate. |
| B-C | `hs/gitutil.py:46` | `snapshot()` sets `idx = real` (the actual `.git/index`) instead of a temp copy, so `GIT_INDEX_FILE` points at the real index during the snapshot's `git add -A`. |

Why each is a real defect:

- **B-A**: `_same_ref` gates the red→green proof check in `verdict()` (§6.4) — with it always `True`, a red-proof's `ref` can mismatch the implementation's `proof_ref` and still pass, so a stale or wrong test run is accepted as proof.
- **B-B**: an agent can supply a `test_cmds` entry that fails and the gate still reports `tests_ok=True` as long as the config `test_cmd` passes, defeating the purpose of letting agents add scoped test commands.
- **B-C**: `snapshot()`'s whole point (per its own docstring) is pinning the working tree without touching the real index; pointing `GIT_INDEX_FILE` at the real index means the snapshot's `git add -A` stages into the user's actual index.

See `diff.patch` for the full unified diff against main `hs/`.

## Scoring recall

`score.py` takes a reviewer's output and prints a recall table:

```
python3 evals/fixtures/seeded-bugs/score.py <REVIEW out.json>      # v1.0 hs schema (hs/schemas.py REVIEW)
python3 evals/fixtures/seeded-bugs/score.py --md <review.md>       # 0.16.2-style `| R-n | severity | tag | file:line | desc |` table
```

A bug counts as:

- **caught** — some finding has severity `blocker`, its `file` basename matches the bug's file, and its `desc` (lowercased) contains one of the bug's keywords (names the mechanism, not just the file).
- **partial** — same file+keyword match, but the best matching finding is severity `major` instead of `blocker`.
- **miss** — no finding matches both file and keyword, or the only matches are `minor`.

Output ends with `recall: N/3 (partials: M)`.
