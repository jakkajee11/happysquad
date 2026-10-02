# Bench tasks — happysquad repo (Q7: this repo is the bench)

Five tasks on `hs/` (python3 stdlib), each with an existing test file to extend under `evals/`.
Run each with 0.16.2 (`/happysquad-loop`) and v1.0 (`/hs-loop`) from a clean checkout of the same
commit, in a throwaway worktree. Record per run: terminal state, iterations, dispatches, asks,
manual resumes, destructive actions, $ cost, and the oracle result (`python3 evals/cov.py -p test_hs.py`
exits 0 after COMPLETE).

Config used by both: `.happysquad/config.json` at repo root (build = py_compile, test = cov.py, threshold 50; cli.py and machine.py start at 0 to 12% under test_hs.py alone, so 70 would make B1/B2 unwinnable by construction).

| # | task | touches | oracle |
|---|---|---|---|
| B1 | `hs status` prints `coverage` (verified_coverage) and `cmds` when present; add tests in `evals/test_hs.py` for the status dict builder (extract it to `hs.cli.status_dict(st)` first) | hs/cli.py, evals/test_hs.py | `python3 bin/hs status` includes `coverage` key on a COMPLETE run |
| B2 | `hs config --json-schema` prints the DEFAULTS structure with types (str/int/bool/null/list/dict) instead of values; test in `evals/test_hs.py` | hs/config.py, hs/cli.py, evals/test_hs.py | key set equals DEFAULTS, every leaf is a type name |
| B3 | `provenance.classify` accepts `allowed_flags` entries of the form `--flag=*` as prefix matches (so `--test-name-pattern=foo` passes when `--test-name-pattern=*` is allowed); tests in `evals/test_hs.py` | hs/provenance.py, evals/test_hs.py | existing Provenance tests still pass; new case passes |
| B4 | `coverage.parse` supports Go `coverprofile` (`mode: set` header, `file:start.col,end.col stmts count` rows) with per-file percentages; fixture + tests in `evals/test_hs.py` | hs/coverage.py, evals/test_hs.py | parse of a 3-file fixture gives expected totals |
| B5 | `machine.verdict`: a `findings[]` row with `severity: blocker` and `tag: STD` is downgraded to `major` (STD never blocks, like SIMPL); tests in `evals/test_hs.py` | hs/machine.py, evals/test_hs.py | verdict with only an STD blocker → PASS, route None |

Seeded-bug recall fixture (separate deliverable, `evals/fixtures/seeded-bugs/`): three defects planted in a
copy of `hs/` for the reviewer axis — (1) `_same_ref` returns True for any two non-empty strings,
(2) `gate_test` ignores `exit != 0` on agent-supplied `test_cmds`, (3) `snapshot` uses the real index
instead of a temp copy. Recall = how many of the three each reviewer prompt flags as blocker.

Baseline (0.16.2) and v1.0 results are appended below as they are collected.

## Results

| task | engine | state | iters | dispatches | asks | resumes | destructive | cost USD | oracle |
|---|---|---|---|---|---|---|---|---|---|
