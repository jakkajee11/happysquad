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
| B1 | 0.16.2 | COMPLETE | 1 | 4 | 0 | 0 | 0 | 5.15 | pass (cov 23.2%, 811s) |
| B2 | 0.16.2 | COMPLETE | 1 | 4 | 0 | 0 | 0 | 5.23 | pass (cov 26.1%, 924s) |
| B3 | 0.16.2 | COMPLETE | 2 | 5 | 0 | 0 | 0 | 6.26 | pass (cov 24.3%, 1089s) |
| B4 | 0.16.2 | COMPLETE (after harness kill + resume) | 2 | 8 | 0 | 1 | 0 | 3.29 + unknown first segment | pass (cov 22.5%, 1997s resume segment) |
| B5 | 0.16.2 | COMPLETE | 1 | 4 | 0 | 0 | 0 | 3.91 | pass (cov 21.2%, 667s) |
| B1 | hs 1.0 headless | COMPLETE | 1 | 5 | 0 | 0 | 0 | 0.77 | pass (oracle cov 13.14%, 475s) |
| B2 | hs 1.0 headless | COMPLETE | 1 | 4 | 0 | 0 | 0 | 0.92 | pass (oracle cov 16.13%, 463s) |
| B3 | hs 1.0 headless | COMPLETE | 1 | 4 | 0 | 0 | 0 | 0.36 | pass (oracle cov 12.75%, 202s) |
| B4 | hs 1.0 headless | COMPLETE | 1 | 4 | 0 | 0 | 0 | 0.63 | pass (oracle cov 13.46%, 467s) (+PROGRESS.md: 0.16 Stop hook nag, see notes) |
| B5 | hs 1.0 headless | COMPLETE | 1 | 5 | 0 | 0 | 0 | 0.62 | pass (oracle cov 12.71%, 232s) |

Baseline notes (0.16.2, sonnet on every agent, cap 3, threshold 50, all five launched in parallel 2026-10-02 18:25 UTC):

- **B2 scope creep:** the squad also edited `evals/bench/tasks.md` (wrote its own results row). Not asked for; the 0.16 chief reviewer PASSed it. The removed requirement-reviewer owned this check; in v1.0 the ownership map refuses it mechanically.
- **B3 took 2 iterations** because the evidence gate rejected the tester's first red→green rows and re-dispatched the tester (not a review FAIL). Second pass: every row assertion-red.
- **B4 iteration-1 REVIEW FAIL → architecter:** the design put the Go fixture at `evals/fixtures/coverage/coverage.out`, which the repo's unanchored `coverage/` gitignore line swallowed, so `git add` failed. That is a repo bug introduced with `evals/cov.py` (fixed: anchored to `/coverage/`). Iteration 2 redesigned to `evals/fixtures/go-cover/`, IMPLEMENT was skipped (design-only change), TEST passed, and the run was in REVIEW when the harness's 60-minute background limit killed the `claude -p` process. Resumed once with `/squad-resume` (counted as 1 manual resume). First-segment cost is unknown because the stream has no result line.
- **Destructive-action matcher:** `rm -rf` of a `/tmp` red→green worktree is the tester's own cleanup and is not counted.
- **B4 resume segment:** `/squad-resume` re-entered at REVIEW i2, the chief reviewer PASSed, 8 dispatches total across both segments (5 before the kill, 3 after: review re-dispatch plus two the resume protocol re-ran), $3.29 for the segment alone, 33 min. Oracle pass; `evals/fixtures/go-cover/coverage.out` plus parser and tests landed.
- **Cost:** measured $23.84 across five runs, plus B4's unmeasured first segment (estimate $4–5 from its 682 stream lines, similar to B1/B2). Call it ≈ $28, almost double the ~$15 in spec §18.2. B3's extra iteration, B4's architecter round plus resume, and B2's wider diff account for it.

- **0.16 coverage gate not enforced (inferred).** Config set `coverage_threshold: 50`; 0.16's reviewer rules gate per-file coverage of touched files. Before B1, `hs/cli.py` was at 0% (230 executable lines); B1 raised total hits by 30 lines, so cli.py ended ≤ 13% even if every new hit landed there. B2 (cli.py + config.py, both 0% before) is the same shape. All five PASSed. Verdict-side coverage enforcement is exactly what v1.0 moves into code (`G-COV` synthetic blocker) — and at threshold 50 per-file, B1/B2/B5 will be hard for hs unless the tester lifts those files substantially. Decide the P2 threshold (or switch to a per-file *delta* rule) before the v1.0 side runs.

**hs 1.0 (headless driver, sonnet on every agent, cap 3, coverage rule delta, in-place, 2026-10-03, engine 9ce4b16):**

- 5/5 COMPLETE at iteration 1, 22 dispatches total, 0 asks, 0 manual resumes, 0 agent errors, 0 heals, oracle 5/5 pass.
- **Cost: $3.30 total ($0.36–$0.92 per task) vs $23.84+ for 0.16.2** — about 7× cheaper per COMPLETE. The headless driver spends no orchestrator LLM turns; every dollar goes to the four agents.
- **Wall clock: 202–475 s per task** vs 667–1997 s for 0.16.2.
- **Unrequested file change (1):** B4 also wrote `PROGRESS.md`. Cause: the bench loads the plugin with `--plugin-dir`, so the 0.16 `stop-sync-check.sh` Stop hook still runs inside the child and nags the agent to journal; `HS_CHILD=1` silences only the v1 `hs hook` command. Not scope creep by the squad; fix in P3 by making the 0.16 hook honour `HS_CHILD` (or by removing it). Counted as 1 destructive/unrequested edit for honesty; it is outside `owned` and the conflict gate would refuse it in parallel mode.
- **Coverage figures are not comparable across engines:** the oracle's whole-package percent fell from ~21–26% to ~13–16% because the engine grew from 1,408 to ~2,370 executable lines between the baseline and this run (same hit count). The v1.0 gate uses the delta rule (added lines only), which every task passed.
- **Two engine bugs found by this bench and fixed before the runs counted:** snapshot failing when the repo's own `.gitignore` ignores `.happysquad/` (586a17a); an in-iteration architect re-run reusing the phase dir (fb056b9).

**Seeded-bug recall (evals/bench/recall.sh, sonnet, same planted diff):** 0.16.2 reviewer 3/3 caught (+1 extra SEC cross-reference), $0.35, 33 turns. hs reviewer: see row below when run.

| reviewer | B-A | B-B | B-C | recall | cost |
|---|---|---|---|---|---|
| 0.16.2 `agents/reviewer.md` | caught | caught | caught | 3/3 | $0.35 |
| hs `agents/hs-reviewer.md` | pending | pending | pending | pending | pending |

**Baseline summary for the P2 dogfood gate (spec §1.2):** false COMPLETE 0/5 · manual resumes 1/5 (B4, harness-caused) · destructive 0/5 · BLOCKED 0/5 · recall: 1 scope-creep miss (B2) · $/COMPLETE ≈ $5.6 measured.
