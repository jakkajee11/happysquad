# happysquad v1.0 — rewrite spec

Status: DRAFT v3 (2026-10-02, post-brainstorm `20261002-225930-bs-v1-rewrite-spec-review`, full-consensus after amendment, + 4 owner decisions) · Owner: พี่จี · Baseline: happysquad 0.16.2

v2 รวม amendment A1 (7 ข้อ), defer list A2, phase ใหม่ A3 และ reviewer notes จาก brainstorm v3 เพิ่มการตัดสินใจของพี่จี 4 ข้อ: Q1 ปิด (refactor COMPLETE ได้), Q2 ปิด (headless ใช้ isolated worktree เป็น default), agent command ต้องตรง config แบบ prefix เต็ม, P1 แยกเป็น P1a/P1b, และ hs เป็น package หลายไฟล์

## 0. ทำไมต้องรื้อ

0.16.2 ให้ orchestrator ที่เป็น LLM อ่าน prose 7,000 คำแล้วทำงาน deterministic เองทุกรอบ (อัปเดต state, รัน gate, parse marker, regex risk, convergence) ผลคือทำพลาดได้ทุกรอบ กิน context ก่อนเริ่มงาน เทสไม่ได้ และทุก release แก้ wait/recover logic โดยไม่มี regression test

หลักเดียวของ v1.0: **LLM ทำเฉพาะงานที่ต้องใช้วิจารณญาณ (ออกแบบ เขียนโค้ด เขียนเทส รีวิว) กลไกทั้งหมดเป็นโค้ดที่เทสได้โดยไม่เรียก model**

สิ่งที่คงไว้จาก 0.16: artifact hand-off, marker เป็น claim, evidence gate, red→green proof, Verify ต่อ finding, inner fix loop + delta review, convergence detection, split-on-risk, wiki read-back, fleet ใน worktree, brainstorm 3 รอบ, cross-session resume

**ความเสี่ยงที่ใหญ่ที่สุดไม่ใช่ logic ของ hs** แต่คือ (1) LLM driver จะทำตาม `next/advance/wait` ได้โดยไม่ต้องช่วยไหม และ (2) gate ที่รันนานจะรอด timeout ของ Bash tool ไหม ทั้งสองข้อตอบด้วย P0 spike (§19) ก่อนเขียน P1

## 1. เป้าหมายและตัวชี้วัด

### 1.1 Output metrics (วัดจากโค้ด)

| เป้าหมาย | วัดจาก | 0.16.2 | v1.0 |
|---|---|---|---|
| orchestrator ไม่ต้องอ่าน artifact | ขนาด `squad-loop/SKILL.md` | 7,087 คำ | ≤ 400 คำ |
| state เขียนโดยโค้ดเท่านั้น | จุดที่ LLM เขียน state | ทุก transition | 0 |
| evidence ไม่ผ่านมือ LLM | ที่มาของ coverage / red-green / verdict | agent พิมพ์ | hs คำนวณ |
| เทสได้โดยไม่เรียก model | logic ที่มี unit test | 0 | gates, transitions, convergence, risk, resume, argv, locking |
| รัน autonomous ได้ | AskUserQuestion ใน loop path เมื่อ `interactive=false` | 6+ | 0 |
| งานเล็กจ่ายน้อย | phase ของ bug fix 3 บรรทัด | เท่า feature | lite path |
| prompt ต่อ dispatch | reviewer agent | 3,260 คำ | ≤ 900 คำ |

### 1.2 Outcome metrics (วัดจาก `evals/bench/`, baseline 0.16.2 เก็บใน P0)

benchmark = toy repo + 1 repo จริง, 5 งาน ตัวเลขทุกตัวเป็น count ไม่ใช่ percentage (5 งานวัด % ไม่ได้)

| metric | เป็น gate ไหม | เกณฑ์ |
|---|---|---|
| false COMPLETE (oracle: รัน `config.build_cmd` + `config.test_cmd` ซ้ำหลัง COMPLETE) | gate | 0 |
| manual resumes or state edits | gate | 0 |
| destructive actions (git push/reset/clean, rm -rf นอก tmp) | gate | 0 |
| BLOCKED count | gate | ≤ baseline |
| seeded-bug recall (fixture 2–3 bug ที่ปลูกไว้) | gate | ≥ baseline ด้วย prompt 0.16.2 |
| unattended completion count | track | รายงานเทียบ baseline |
| $ per COMPLETE | track | แสดงเทียบ baseline ที่ P2 gate |

## 2. Non-goals

### 2.1 ตัดออกจาก core → ย้ายไป plugin `happysquad-ext`

**ตัดสินใจแล้ว (2026-10-02):** ย้ายไฟล์ไป repo `happysquad-ext` (plugin แยก ยังไม่ต้องใช้ได้ใน v1.0) ก่อนลบจาก repo นี้ใน P3

- External executors (glm/opencode), tmux pane rule, quota fallback, mechanical offload (§11 เดิม)
- `/squad-assemble` + team-assembly skill
- `/ask-kilo` + ask-kilo skill
- Fable-specific escalation (§10a เดิม)
- Worktree-per-workstream fallback + merge ด้วย `git diff | git apply` (§8 เดิม)
- `/squad-implement`, `/squad-test` (manual mid-loop step ที่ข้าม gate)
- requirement-reviewer, standard-reviewer (default mode ไม่เคย dispatch)
- "Brainstorm mode" ในทุก agent file → ย้ายไป `prompts/brainstorm/*.md` (P2)
- Git snapshot ใน SessionStart hook

### 2.2 เลื่อนไป 1.1 (consensus A2)

เงื่อนไขจาก product: ไม่มีข้อไหนกลับเข้า v1.0 เว้นแต่ตัดอย่างอื่นออกแลก

- `hs frontier`, `/squad-fleet --frontier` / `--drain`, label `squad:passed` (ตัดเส้นทาง public-issue → `build_cmds` injection ไปด้วย)
- `hs brainstorm` (brainstorm ใช้ orchestration แบบ 0.16 ต่อ แค่ย้าย prompt)
- `hs wiki lint`
- context checkpoint (§8.9 เดิม)
- `--json` / `--brief` ทั่วไป (เหลือ `hs status --brief`)
- `references/skill-map.json` (stack-detector ใช้ mapping ในตัวไปก่อน)
- `escalation.model`

## 3. โครงสร้างไฟล์

```
happysquad/
├── .claude-plugin/plugin.json          # description ประโยคเดียว
├── bin/hs                              # entry: sys.path insert + hs.cli.main()
├── hs/                                 # python3 ≥ 3.9 stdlib package, ไม่มี dependency
│   ├── cli.py                          # argparse, subcommand dispatch, JSON output
│   ├── config.py                       # defaults, schema, effective config
│   ├── state.py                        # state.json / events.jsonl, flock, atomic write
│   ├── schemas.py                      # out.json schemas (source of truth), validate
│   ├── machine.py                      # transitions, routing, verdict, convergence, iteration table
│   ├── gates.py                        # build / test / conflict / verify, _gates runner
│   ├── coverage.py                     # 4 parsers
│   ├── redgreen.py                     # worktree + classify
│   ├── provenance.py                   # command allowlist, shlex, subprocess wrapper
│   ├── gitutil.py                      # snapshot, refs, diff pathspec, prune/sweep
│   ├── render.py                       # prompt templates
│   ├── drivers.py                      # agent-tool action loop, headless, fake (HS_CLAUDE)
│   ├── fleet.py                        # P4
│   └── hooks.py                        # session-start / stop
├── agents/
│   ├── architecter.md                  # ≤ 900 คำ
│   ├── implementer.md                  # ≤ 600
│   ├── tester.md                       # ≤ 800
│   ├── reviewer.md                     # ≤ 900
│   ├── specialist.md                   # ≤ 500 (+ references/axis-*.md ≤ 400 แต่ละอัน)
│   └── product.md                      # ≤ 600 (brainstorm เท่านั้น)
├── prompts/                            # dispatch templates ที่ hs render
│   ├── architect.md  implement.md  test.md  review.md  specialist.md  fix.md
│   └── brainstorm/r1-<agent>.md  r2-<agent>.md  consensus.md  signoff-<agent>.md
├── references/
│   ├── axis-sec.md  axis-perf.md
│   ├── risk-patterns.json
│   ├── out-schemas.json                # generate จาก hs/schemas.py (hs เป็น source of truth)
│   └── design-template.md  design-template-lite.md
├── skills/  squad-loop  fleet  brainstorm  stack-detector  dev-wiki
├── commands/                           # §14
├── hooks/hooks.json                    # เรียก hs hook ...
├── evals/
│   ├── test_hs.py                      # unittest, ไม่เรียก model
│   ├── fake_agent.py                   # fake claude binary
│   ├── fixtures/toy-repo/              # zero-dep node, node --test + lcov
│   ├── fixtures/coverage/              # lcov.info, cobertura.xml, coverage-summary.json, coverage.json + boundary cases
│   ├── fixtures/seeded-bugs/           # repo ที่ปลูก bug 2–3 ตัว สำหรับ recall
│   ├── scenarios/*.json                # fake-driver scenarios
│   ├── bench/                          # 5 งาน + oracle + baseline results (deliverable แยก)
│   └── smoke.sh                        # claude -p จริง 1 loop, budget cap
├── docs/spec/v1-rewrite.md
├── CHANGELOG.md
└── README.md
```

Run directory (hs เขียนทั้งหมด ยกเว้น `config.json`, `risk-patterns.json`):

```
.happysquad/
├── .gitignore                          # hs init เขียน (§17)
├── config.json
├── stack-profile.{md,json}
├── risk-patterns.json                  # optional override
├── current                             # run-id ปัจจุบัน (บรรทัดเดียว)
├── runs/<run-id>/
│   ├── state.json  .lock  events.jsonl
│   ├── task.md  design.md
│   ├── prompts/<PHASE>-i<N>[-<ws>].md
│   ├── <PHASE>-i<N>[-<ws>][-r<k>]/     # phase dir
│   │   ├── out.json                    # agent เขียน
│   │   ├── *.md                        # implementation.md / test-report.md / review.md / sec.md
│   │   ├── redgreen.json  verify.json
│   │   └── logs/*.log
│   ├── gates-<PHASE>-i<N>[-<ws>].json  # hs _gates เขียน
│   ├── conflict.json  risk.json  feedback.md  BLOCKED.md
├── fleets/<fleet-id>/{fleet.json,tasks.md,aggregate-report.md}
├── worktrees/<fleet-id>/<slug>/
└── brainstorms/<session-id>/
```

**Temp ทั้งหมดอยู่นอก working tree:** `$(git rev-parse --git-common-dir)/happysquad/tmp/` ใช้สำหรับ red-green worktree และ temp index ของ snapshot `run start` และ `resume` รัน `git worktree prune` และกวาด directory นี้

## 4. `hs` CLI contract

python3 ≥ 3.9 stdlib เท่านั้น เป็น package `hs/` หลายไฟล์ (§3) โดย `bin/hs` เป็น entry บรรทัดเดียว ไม่ใช่ไฟล์เดียว 2,500 บรรทัด เหตุผล: unit test ต่อ module, import ได้จาก `test_hs.py` โดยไม่ต้อง subprocess ทุกเคส ไม่เพิ่ม dependency ทุกคำสั่งพิมพ์ JSON บรรทัดเดียวบน stdout เว้นแต่ระบุ exit 0 = สำเร็จ, 1 = gate/validation fail (เป็นผลลัพธ์ปกติ), 2 = usage/IO error ทุกคำสั่งรับ `--run <id>` (default: `.happysquad/current`)

| คำสั่ง | ทำอะไร | เขียนอะไร |
|---|---|---|
| `hs init [--non-interactive]` | สร้าง `.happysquad/`, `.gitignore`, `config.json` default; seed `build_cmd` / `test_cmd` / `coverage_report` จาก stack-detector | `.happysquad/*` |
| `hs config` | พิมพ์ effective config (default + file) | – |
| `hs run start "<task>" [--lite\|--full] [--no-parallel] [--driver X]` | prune/sweep tmp, สร้าง run, snapshot base_ref, state=ARCHITECT, คืน action แรก; `test_cmd` null → `ask` หรือ BLOCKED cause=config | state, events, task.md, current |
| `hs next` | idempotent: action ถัดไปตาม state ไม่เปลี่ยน state | prompts/ (render) |
| `hs advance` | consume out.json ที่ค้าง → validate → spawn `hs _gates` (detached) → คืน `wait`; เมื่อ gates เสร็จ → transition → action ถัดไป re-entrant | state, events, feedback.md |
| `hs wait [--timeout 540]` | poll in-process จน out.json / gates file ครบ; คืน action ถัดไป (เรียก advance ให้) หรือ `wait` อีกครั้งเมื่อหมดเวลา | – |
| `hs _gates <phase-dir>` | internal: รัน gate build/test/conflict/verify ของ phase นั้น เขียน `gates-*.json` | gates file, logs |
| `hs gate build\|test\|conflict [--phase-dir D]` | รัน gate เดี่ยวแบบ foreground (manual/debug) | gate output |
| `hs redgreen --ref R --tests F... [--cmd T] [--copy P...] [--link P...]` | red proof ใน throwaway worktree ทีละไฟล์ | redgreen.json |
| `hs verify <out.json>` | รัน `verify` ของทุก finding ตามกฎ provenance (§7.0) | verify.json |
| `hs validate <out.json> [--phase P]` | ตรวจ schema เดียวกับ advance; agent เรียกก่อนจบ | – |
| `hs risk` | regex บน diff vs base_ref | risk.json |
| `hs snapshot` | pinned ref ของ working tree (§17) | พิมพ์ sha |
| `hs status [--brief]` | สรุป run/fleet/brainstorm ≤ 40 บรรทัด | – |
| `hs resume` | prune/sweep, หา candidate ที่ค้าง, recover จาก out.json บนดิสก์, คืน action | state, events |
| `hs answer <key> <value>` | ตอบ `ask` action | state |
| `hs block "<reason>" [--cause agent\|config]` | บังคับ BLOCKED | BLOCKED.md |
| `hs fleet start <tasks-file> [--max N]` | สร้าง worktrees, fleet.json (P4) | fleets/, worktrees/ |
| `hs fleet advance` | reconcile children, คืน children ที่ต้อง dispatch/wait (P4) | fleet.json |
| `hs hook session-start\|stop` | hook bodies; `HS_CHILD=1` → exit 0 เงียบ | `.happysquad/.session` |

### 4.1 Action schema

```json
{"action":"dispatch","phase":"ARCHITECT","iteration":1,"agent":"architecter","model":"opus",
 "prompt_file":".happysquad/runs/R/prompts/ARCHITECT-i1.md",
 "out_file":".happysquad/runs/R/ARCHITECT-i1/out.json","workstream":null,"cwd":null}

{"action":"dispatch_many","phase":"IMPLEMENT","wave":1,"dispatches":[{...},{...}]}

{"action":"wait","for":"agents|gates","files":["..."],"since":"2026-10-02T10:00:00Z"}

{"action":"ask","key":"resume_existing","question":"...","options":["resume","restart","new"],"default":"resume"}

{"action":"done","status":"COMPLETE|BLOCKED","cause":null,"run_id":"R","iterations":2,
 "files_changed":12,"coverage":84.2,"report":".happysquad/runs/R/REVIEW-i2/review.md",
 "suggested_commit":"feat: ...","wiki_offer":true}
```

`ask` ออกเฉพาะ `interactive=true` ถ้า `false` hs ใช้ default ตาม §16.2 แล้วเดินต่อเอง

## 5. State model

### 5.1 `runs/<run-id>/state.json` (hs เขียนเท่านั้น)

```json
{"run_id":"20261002-101500-add-api-key-auth","task":"...","driver":"agent-tool",
 "mode":"single|parallel","lite":false,"size":"M",
 "base_ref":"refs/happysquad/<run>/base","iter_ref":null,
 "state":"IMPLEMENT","iteration":1,"inner_pass":0,"gate_retry":0,"validation_retry":0,
 "cap":5,"inner_cap":2,"coverage_threshold":80,"review_mode":"split-on-risk",
 "cmds":{"build":["pnpm build"],"test":["pnpm test -- --coverage"],"coverage_report":"coverage/lcov.info"},
 "workstreams":[{"name":"backend","owned":["src/auth/**","src/routes.ts"],"depends_on":[],"ac":["AC-1"],
                 "impl":"pending|dispatched|done","test":"pending|dispatched|done"}],
 "untestable":[{"ac":"AC-4","reason":"docs only"}],
 "pending":[{"phase":"IMPLEMENT","iteration":1,"workstream":"backend",
             "out_file":"...","dispatched_at":"..."}],
 "gates":{"IMPLEMENT-i1-backend":{"pid":12345,"file":"gates-IMPLEMENT-i1-backend.json","started_at":"..."}},
 "findings":{"R-1":{"fp":"<sha1>","seen":[1,2],"routes":["implementer","implementer"]}},
 "parent_fleet_id":null,"worktree":null,
 "started_at":"...","updated_at":"..."}
```

### 5.2 `events.jsonl` (append-only)

หนึ่งบรรทัดต่อเหตุการณ์ `{"ts","event","phase","iteration","workstream","data"}` events: `run.start`, `dispatch`, `consume`, `validate`, `gates.start`, `gates.done`, `gate.build`, `gate.test`, `gate.conflict`, `risk`, `verify`, `transition`, `review`, `convergence`, `ask`, `answer`, `block` (`data.cause ∈ validation|gate|convergence|agent|config`), `complete`, `resume`, `recover`

### 5.3 Phase directory

`<PHASE>-i<N>[-<ws>]/` retry (gate หรือ validation) ใช้ suffix `-r<k>` ไม่ลบของเก่า

### 5.4 Concurrency และ atomicity

- ทุกคำสั่งที่เขียน state ถือ `fcntl.flock` บน `runs/<id>/.lock` ตลอดคำสั่ง
- เขียนไฟล์ state ทุกตัวแบบ tmp → `fsync` → `os.replace`
- append event **ก่อน** save state เสมอ
- `advance` re-entrant: `pending` entry ที่มี event `consume` แล้วถูกข้าม ไม่ consume ซ้ำ; phase ที่มี `gates.pid` ยังมีชีวิต (`os.kill(pid, 0)`) → คืน `wait` ไม่ spawn ซ้ำ
- clock inject ได้ด้วย `HS_NOW` (ISO string) สำหรับเทส

## 6. Phase output contracts (`out.json`)

ทุก agent จบงานด้วยการเขียน `out.json` ที่ `{{out_file}}` และรัน `{{hs}} validate {{out_file}}` ก่อนจบ ไม่มี marker บรรทัดข้อความ final message ของ agent เป็นอะไรก็ได้

schema ฝังใน hs เป็น dict เดียว ใช้ทั้ง `validate`, `advance` และ render `{{out_schema}}` ลง prompt key ขาด/ผิด type → re-dispatch phase เดิมพร้อม `retry_reason` (`validation_retry += 1`, แยกจาก `gate_retry`) เกิน `validation_retries` (default 2) → BLOCKED cause=validation

### 6.1 ARCHITECT

```json
{"phase":"ARCHITECT","size":"S|M|L","design":"design.md",
 "assumptions":["..."],
 "ac":[{"id":"AC-1","text":"accepts valid API key, returns 200"}],
 "untestable":[{"ac":"AC-4","reason":"docs change, no runtime behaviour"}],
 "workstreams":[{"name":"backend","owned":["src/auth/**","src/routes.ts"],"depends_on":[],"ac":["AC-1","AC-2"]}],
 "test_owned":{"backend":["tests/auth/**"]},
 "shared_read_only":["src/db.ts"]}
```

กฎที่ hs ตรวจ: `owned` รับ fnmatch glob; owned ข้าม workstream ต้องไม่ทับกัน (ทับ → re-dispatch พร้อมเหตุผล ไม่มี worktree fallback); `depends_on` ต้องเป็น DAG; ทุก AC ต้องอยู่ใน workstream ใดสักอันหรือใน `untestable`; ไฟล์ที่ design.md กล่าวถึงด้วย `` `path.ext` `` แต่ไม่อยู่ใน owned → **warning** ใน event ไม่ใช่ gate `size=S` + `lite.auto=true` → lite path (§8.5)

### 6.2 IMPLEMENT (ต่อ workstream)

```json
{"phase":"IMPLEMENT","workstream":"backend",
 "files":["src/auth.ts"],
 "build_cmds":["pnpm lint"],
 "unmet_ac":[{"id":"AC-3","reason":"..."}],
 "design_conflict":null,
 "ownership_gap":null}
```

`build_cmds` เป็นส่วน **เพิ่ม** จาก `config.build_cmd` (gate รัน config ก่อนเสมอ) และต้องผ่านกฎ provenance (§7.0): ต้องเป็น config command แบบ prefix เต็ม + argument เพิ่ม (เช่น `pnpm lint` ผ่านก็ต่อเมื่อ config มี `pnpm lint` หรือ `pnpm`-prefixed command ที่ขยายได้ตามกฎ) ส่วนใหญ่ของ v1.0 คาดว่า `build_cmds` จะว่าง `ownership_gap: {"file","reason"}` หรือ `design_conflict: "<text>"` → route ARCHITECT พร้อม feedback hs ตรวจว่า `files` ⊆ owned และ (single run) diff ⊆ owned

### 6.3 TEST (ต่อ workstream)

```json
{"phase":"TEST","workstream":"backend",
 "test_cmds":["pnpm test -- tests/auth"],
 "coverage_report":null,
 "test_files":["tests/auth.test.ts"],
 "new_tests":["tests/auth.test.ts"],
 "ac_map":{"AC-1":["tests/auth.test.ts::rejects expired key"]},
 "untestable":[{"ac":"AC-5","reason":"requires live SMS provider"}],
 "redgreen":"redgreen.json",
 "findings":[{"ac":"AC-2","desc":"impl returns 500 not 401"}]}
```

- `test_cmds` เพิ่มจาก `config.test_cmd`; `coverage_report` null = ใช้ config
- tester ต้องเรียก `{{hs}} redgreen --ref {{proof_ref}} --tests <new_tests>` เอง (hs ทำ worktree ทั้งหมด)
- `ac_map` ต้องครอบคลุมทุก AC ของ workstream ที่ไม่อยู่ใน `untestable` (จาก ARCHITECT หรือ TEST) ไม่งั้น validation fail
- `new_tests` ว่างได้ (refactor/docs/config) → hs inject TEST **major** "no red-first proof" ให้ reviewer ตัดสิน **Q1 ปิดแล้ว:** run แบบนี้ COMPLETE ได้ถ้า reviewer ไม่ยกเป็น blocker ไม่งั้น lite path สำหรับ docs/config ไม่มีวันจบ reviewer ยก major นี้เป็น blocker ได้เมื่อเห็นว่า diff เปลี่ยน behaviour ที่ควรมี test (ระบุใน `agents/reviewer.md`)

### 6.4 REVIEW (chief) และ SPECIALIST

```json
{"phase":"REVIEW","mode":"single|split-on-risk|delta",
 "report":"review.md",
 "findings":[
  {"id":"R-1","prior_id":null,"severity":"blocker|major|minor","tag":"REQ|SEC|PERF|STD|SIMPL|TEST|CONFLICT",
   "file":"src/auth.ts","line":42,"desc":"API key compared with == not const-time",
   "route":"implementer|tester|architecter","workstream":"backend",
   "verify":"! grep -qE 'apiKey\\s*==' src/auth.ts","source":"self|sec|perf"}],
 "overrides":[{"id":"S-2","reason":"false positive: value is a public prefix"}],
 "axes":{"REQ":"PASS","SEC":"FAIL","PERF":"PASS","STD":"PASS","SIMPL":"PASS","TEST":"PASS"},
 "confirmed_fixes":["R-1"]}
```

**Verdict คำนวณโดย hs จาก truth table นี้** (reviewer ไม่ส่ง verdict) ทุก term ที่ fail กลายเป็น synthetic blocker `source:"gate"` verdict = PASS ก็ต่อเมื่อ blocker (รวม synthetic) เป็นศูนย์ FAIL โดยไม่มี blocker จึงเกิดไม่ได้

| term | PASS เมื่อ | ไม่งั้น |
|---|---|---|
| tests | `config.test_cmd` (full suite) exit 0 | REQ blocker → implementer, `verify = config.test_cmd` |
| coverage | per-file ของ `IMPLEMENT.files` ≥ threshold (inclusive); `coverage_threshold: null` → ข้าม term | ต่ำกว่า → TEST blocker → tester; status `unsupported` (ไม่มี parser) → ข้าม term + TEST major; status `unparseable` → gate fail, re-dispatch tester |
| redgreen | ทุกแถวของ `new_tests` มี, `ref == proof_ref`, ไม่มีแถว `green` | TEST blocker → tester |
| `new_tests` ว่าง | อนุญาต (Q1 ปิด: refactor/docs/config COMPLETE ได้) | TEST major "no red-first proof"; reviewer ยกเป็น blocker ได้เมื่อ diff เปลี่ยน behaviour |
| specialist blockers | union เข้า verdict | ถอดได้เฉพาะผ่าน chief `overrides[{id,reason}]` |
| reviewer blockers | ไม่มี | FAIL, route ตาม finding |

route: มี CONFLICT → architecter; มี blocker route=architecter → architecter; ไม่งั้น set ของ route ใน blockers `SIMPL` severity บังคับ ≤ major `prior_id` ชี้ finding รอบก่อน (จากตาราง `{{prior_findings}}`) hs ใช้เป็นหลัก fingerprint เป็น fallback (§8.3)

SPECIALIST: `{"phase":"SPECIALIST","axis":"sec|perf","report":"sec.md","findings":[...]}` ไม่มี `route`/`verify` chief เติม

## 7. Gates (ทั้งหมดใน hs)

### 7.0 Command provenance และ subprocess rules

- `config.build_cmd`, `config.test_cmd`, `config.coverage_report` seed โดย `hs init` จาก stack-detector เป็น **authoritative** gate รันเสมอ seed ผิด → BLOCKED cause=gate ที่ gate แรก user แก้ `config.json` แล้ว resume
- `test_cmd` null ตอน `run start` → `ask` (interactive) หรือ BLOCKED cause=config **ก่อน** ARCHITECT (ไม่เสียเงิน)
- command จาก agent (`build_cmds`, `test_cmds`, `verify`) เป็นส่วนเพิ่มเท่านั้น รันด้วย `shlex.split` + `shell=False` และรับเฉพาะเมื่อตรงกฎข้อใดข้อหนึ่ง (ตัดสินใจแล้ว: **prefix เต็ม ไม่ใช่แค่ argv[0]** เพราะ `pnpm` ใน allowlist จะปล่อย `pnpm exec <anything>` และ `pnpm run <script ที่ agent เพิ่มเอง>` ผ่าน):
  1. argv ของ agent command ขึ้นต้นด้วย argv **ทั้งหมด** ของ config command ตัวใดตัวหนึ่ง (`config.build_cmd` หรือ `config.test_cmd` หลัง `shlex.split`) และ argument ที่เพิ่มต้องไม่ขึ้นต้นด้วย `-` ยกเว้นอยู่ใน `config.allowed_flags` (default: `--run`, `--filter`, `--grep`, `-t`, `-k`, `--testNamePattern`, `--coverage`) และต้องไม่มี token ใดเป็น `exec`, `run`, `dlx`, `x`, `--`, `-c`, `-e`
  2. argv[0] ∈ {`grep`, `rg`, `test`, `[`} (สำหรับ `verify` เท่านั้น) argument เป็น literal ไม่มี `-f`/`--file`
  3. leading `!` hs จัดการเอง (negate exit code)
- `test_cmds` ที่ตรงกฎ 1 ใช้ได้เฉพาะเป็น scope ของ `test_cmd` (เช่น `pnpm test -- tests/auth`) gate เต็มยังรัน config เสมอ
- **reject เสมอ** ไม่ว่าตรง prefix ไหม: token ใด ๆ เป็น `sh`, `bash`, `zsh`, `env`, `xargs`, `npx`, `pnpm dlx`, `npm exec`, `yarn dlx`, `python -c`, `node -e`, `eval`, หรือมี `|`, `;`, `&&`, `||`, `>`, `<`, `$(`, backtick (shlex ไม่ตีความอยู่แล้ว แต่ reject ให้ชัดเพื่อไม่ส่งเป็น literal arg ที่ runner อาจตีความต่อ)
- command ที่ไม่ผ่าน → event `untrusted` พร้อมเหตุผล; `verify` กลายเป็น `manual`; `build_cmds`/`test_cmds` ถูกทิ้ง
- ผลข้างเคียงที่ยอมรับ: `verify` ที่ซับซ้อนตกเป็น `manual` มากขึ้น → inner fix น้อยลง full round มากขึ้น แลกกับไม่มี LLM-controlled exec ใน hs
- ทุก subprocess: `start_new_session=True`, timeout → `os.killpg`
- **ไม่มีงานยาวใน foreground**: `advance` spawn `hs _gates <phase-dir>` แบบ detached (double-fork หรือ `Popen` + `start_new_session`) บันทึก pid ใน `state.gates` แล้วคืน `wait` `hs wait` poll จน gates file เขียนเสร็จ (atomic rename) แล้ว transition ภายใน timeout เดียวกัน (default 540s < Bash 600s) phase ที่ pid ยังมีชีวิต → `wait` ไม่ spawn ซ้ำ

### 7.1 `hs gate build`

รัน `config.build_cmd` แล้ว `build_cmds` ที่ผ่าน provenance ตามลำดับ cwd = repo (หรือ worktree) timeout `gate_timeout` log ไป `logs/build-<n>.log` ผล `{"ok":true,"cmds":[{"cmd":"pnpm build","exit":0,"log":"...","source":"config|agent"}]}` fail → feedback.md ส่วน `## Gate failure` (command, exit, log tail 20 บรรทัด) → re-dispatch implementer เดิม (`gate_retry += 1`) เกิน `gate_retries` → BLOCKED cause=gate

### 7.2 `hs gate test`

1. รัน `config.test_cmd` (full suite) แล้ว `test_cmds` ที่ผ่าน provenance เก็บ exit + log
2. อ่าน coverage report (config หรือ TEST override) รองรับ 4 format ด้วย stdlib: `lcov.info` (LF/LH), cobertura `*.xml` (`line-rate`), istanbul `coverage-summary.json` (`total.lines.pct`), pytest-cov `coverage.json` (`totals.percent_covered`) ทั้ง total และต่อไฟล์ status: `ok` | `missing` (ไฟล์ไม่มี → เหมือน `unsupported`) | `unsupported` (format ไม่รู้จัก) | `unparseable` (format รู้จักแต่ parse ไม่ได้)
3. per-file coverage ของ `IMPLEMENT.files` ใน workstream เทียบ threshold แบบ inclusive (`>=`) เทสต้องมีกรณีเท่ากับ threshold พอดีและบวกลบหนึ่งบรรทัด
4. ตรวจ `redgreen.json` ตาม truth table
5. ผล `{"ok":bool,"tests":"pass|fail","coverage":{"status":"ok","total":84.2,"per_file":{...}},"redgreen":{"assertion":3,"compile":2,"not_runnable":0,"all_compile":false}}`

test fail ที่ `TEST.findings` อธิบายไว้ → ส่งต่อ review (term `tests` ยัง FAIL → synthetic blocker) test fail ที่ไม่มี findings → feedback + re-dispatch tester

### 7.3 `hs redgreen`

```
hs redgreen --ref <ref> --tests tests/a.test.ts tests/b.test.ts \
            [--cmd "pnpm test -- {file}"] [--copy fixtures/x.json] [--link node_modules vendor .env.testing]
```

1. `git worktree add --detach <git-common-dir>/happysquad/tmp/red-<phase>-<pid> <ref>` (ref null หรือ add fail → ทุกแถว `not-runnable` พร้อมเหตุผล)
2. copy `--tests` + `--copy` ไป path เดียวกัน symlink `--link` (default: `node_modules vendor .venv .env.testing` ถ้ามี)
3. รัน `--cmd` **ทีละไฟล์เทส** โดยแทน `{file}` (default: `config.test_cmd` + ` {file}`) timeout 600s ต่อไฟล์
4. classify ต่อไฟล์: exit 0 → `green`; output match compile/import regex (`Cannot find module|ModuleNotFoundError|cannot find symbol|error TS\d+|SyntaxError|ImportError|undefined reference|package .* is not in`) → `compile`; ไม่งั้น `assertion`
5. `git worktree remove --force` ใน `finally` เสมอ; `run start`/`resume` prune ซ้ำกันพลาด
6. `redgreen.json`: `{"ref":"<sha>","rows":[{"test":"tests/a.test.ts","kind":"assertion","evidence":"<last 5 lines>"}]}`

tester ห้ามแตะ worktree เอง ห้าม mutate production code เพื่อพิสูจน์ `workspace:*` / monorepo: ดู Q4 §20

### 7.4 `hs gate conflict` (parallel เท่านั้น)

1. `changed = git diff --name-only base_ref -- . ':(exclude).happysquad' ':(exclude)knowledge'` ∪ `git ls-files --others --exclude-standard` (exclude เดียวกัน)
2. ไฟล์ที่ตรง `config.generated` glob (lockfile, `**/__snapshots__/**`) ยกเว้นจากข้อ 3
3. ทุกไฟล์ที่เหลือต้อง match `owned` ∪ `test_owned` (fnmatch) ของ workstream เดียวพอดี
4. integration: `config.build_cmd` + `config.test_cmd`
5. `conflict.json`: `{"ok":bool,"violations":[{"file":"...","owners":[...],"reason":"unowned|multi-owner"}],"integration":{"exit":0}}` fail → ARCHITECT, `iteration += 1`

single/lite: ข้าม เขียน `{"ok":true,"skipped":"single"}`

### 7.5 `hs verify`

รันทุก `verify` ที่ไม่ใช่ `manual` ตามกฎ §7.0 timeout 300s `verify.json`: `{"R-1":"pass","R-2":"fail","R-3":"manual","R-4":"untrusted"}` (`untrusted` นับเป็น manual ตอนตัดสิน inner-loop eligibility)

### 7.6 `hs risk`

patterns จาก `references/risk-patterns.json` merge กับ `.happysquad/risk-patterns.json`:

```json
{"sec":{"paths":["(?i)auth","(?i)token","(?i)secret","(?i)payment"],
        "diff":["(?i)cors","Content-Security-Policy"],
        "manifest_deps":true},
 "perf":{"paths":["(?i)migration","(?i)queue","(?i)worker"],
         "diff":["\\bSELECT\\b","\\.findMany\\(","fetch\\(","(?i)cache"]}}
```

ทำงานบน diff ที่ exclude `.happysquad` และ `knowledge` แล้ว ผล `risk.json`: `{"axes":["sec"],"matches":[{"file":"src/auth.ts","axis":"sec","pattern":"(?i)auth"}]}`

## 8. State machine

```
ARCHITECT ──▶ IMPLEMENT(waves) ──▶ TEST(waves) ──▶ CONFLICT ──▶ RISK ──▶ SPECIALISTS ──▶ REVIEW ──┬─▶ COMPLETE
   ▲                                                                                              │
   │◀────────────── route=architecter / CONFLICT fail / ownership_gap / design_conflict ◀──────────┤
   │                                                                                              │
   │         ┌──── all blockers verifiable ────▶ INNER_FIX ──▶ verify ──▶ gates ──▶ REVIEW(delta)
   │         │
   └── FAIL ─┴──── any manual/untrusted blocker ─▶ IMPLEMENT/TEST (subset) ──▶ ... ──▶ REVIEW
```

ทุกลูกศรที่ออกจาก IMPLEMENT/TEST/INNER_FIX ผ่าน `hs _gates` (detached) ก่อน

### 8.1 กฎ transition

- `ARCHITECT` ok → `IMPLEMENT` wave 1 (`parallel=false` หรือ `--no-parallel` → workstream เดียว) ก่อน dispatch แรกของทุก iteration > 1: `iter_ref = hs snapshot`
- ทุก `IMPLEMENT` wave จบ → gate build ต่อ workstream → wave ถัดไป → ครบ → `TEST` wave 1 (DAG เดียวกัน)
- ทุก `TEST` wave จบ → gate test ต่อ workstream
- `CONFLICT` → `RISK` → `SPECIALISTS`: dispatch specialist ต่อ axis ใน `risk.json` พร้อมกัน (`dispatch_many`) **รอครบ** → `REVIEW`: dispatch chief พร้อม path ของ specialist reports (ไม่ parallel กับ chief — ตัดสินใจแล้ว §20)
- `REVIEW` → hs คำนวณ verdict (§6.4) → `COMPLETE` หรือ routing (§8.2)
- `iteration > cap` → BLOCKED cause=convergence

**ตาราง iteration increment (ที่เดียว):**

| เหตุการณ์ | iteration |
|---|---|
| FAIL → full round (IMPLEMENT/TEST subset หรือ ARCHITECT) | +1 |
| FAIL → INNER_FIX (delta review คือ review ของรอบนี้) | +1, `inner_pass=0` |
| delta review FAIL, `inner_pass < inner_cap` | +0, `inner_pass += 1` |
| delta review FAIL, `inner_pass == inner_cap` → full round | +1 |
| CONFLICT fail → ARCHITECT | +1 |
| `ownership_gap` / `design_conflict` ครั้งแรกของ run | +0 |
| `ownership_gap` / `design_conflict` ครั้งถัดไป | +1 |
| gate retry / validation retry | +0 (counter แยก) |

### 8.2 Routing เมื่อ FAIL

1. เขียน `feedback.md` (§9.3)
2. convergence (§8.3) อาจ override route
3. route ∈ {implementer, tester} ∧ ทุก blocker `verify ∉ {manual, untrusted}` ∧ `inner_pass < inner_cap` → `INNER_FIX`: dispatch fix agent (implementer ก่อน tester) ด้วย `prompts/fix.md` → `hs _gates` รัน verify → ทั้งหมด pass → gate build + test เต็ม → CONFLICT (parallel) → `REVIEW` mode `delta` (chief เท่านั้น เว้นแต่ `hs risk` บนไฟล์ที่ fix แตะเจอ axis ใหม่)
4. ไม่งั้น full round: `IMPLEMENT`/`TEST` subset หรือ `ARCHITECT`

### 8.3 Convergence

หลัก: chief ส่ง `prior_id` เทียบตาราง `{{prior_findings}}` ที่ hs ใส่ใน prompt fallback: `fp = sha1(tag|file|normalize(desc))` (lowercase, ตัด digits/quotes/whitespace, ตัด token > 40 ตัว) hs เป็นคนนับ `seen` เสมอ

- seen ครั้งที่ 2 → route ปกติ
- seen ครั้งที่ 3 → บังคับ `architecter`
- seen หลัง iteration ที่ route=architecter → BLOCKED cause=convergence
- รอบที่ `resolved = 0` → บังคับ `architecter`; สองรอบติด → BLOCKED

### 8.4 Retry counters

| counter | เพิ่มเมื่อ | เกินแล้ว |
|---|---|---|
| `validation_retry` | out.json ไม่ผ่าน schema | `validation_retries` (2) → BLOCKED cause=validation |
| `gate_retry` | gate build/test fail ที่ re-dispatch agent เดิม | `gate_retries` (1) → BLOCKED cause=gate |
| `agent_retry` (driver นับ) | Agent tool error / `claude -p` exit ≠ 0 | 1 → `hs block --cause agent` |

reset counter เมื่อ phase ผ่าน phase dir ใช้ suffix `-r<k>`

### 8.5 Lite path

เข้าเมื่อ `--lite` หรือ (`size=S` ∧ `lite.auto`) ∧ ไม่ `--full`: design ใช้ `design-template-lite.md`, workstream เดียว, ข้าม CONFLICT/RISK/SPECIALISTS, `review_mode=single`, cap = `lite.cap` (3) red→green, gates, inner fix, convergence ยังทำครบ

### 8.6 BLOCKED

`BLOCKED.md`: cause (`validation|gate|convergence|agent|config`), task, ตาราง iteration/verdict/route จาก events, blockers ปัจจุบัน, convergence (findings, seen, routes, สิ่งที่ลองจาก feedback ทุกรอบ), gate failures, recommended action hs เขียนทั้งหมดจาก events + out.json

### 8.7 Resume และ recovery

`hs resume`:
0. `git worktree prune`, กวาด `<git-common-dir>/happysquad/tmp/`
1. `pending` ที่ `out_file` มีอยู่และยังไม่มี event `consume` → consume (event `recover`)
2. `gates` ที่ pid ยังมีชีวิต → `wait`; pid ตายแต่ไม่มี gates file → spawn ใหม่
3. pending ที่ไม่มี out.json แต่ phase dir ถูกแตะใน 10 นาที (ตาม `HS_NOW`) → `wait`
4. ที่เหลือ → re-dispatch (prompt เดิม)
5. ไม่มี pending → `next`
BLOCKED/COMPLETE ไม่ resume `--run <id>` เลือก run อื่นได้

## 9. Prompts

### 9.1 Template rendering

`prompts/<phase>.md` ใช้ `{{var}}` แทนที่ด้วย `str.replace` ตัวแปร: `hs` (absolute path ของ hs), `out_schema` (render จาก schema dict), `run_id, iteration, task, task_file, design_path, feedback_path, implementation_path, test_report_path, owned_files, test_owned_files, workstream, ac_list, untestable, base_ref, iter_ref, proof_ref, skills, out_file, phase_dir, verified_coverage, threshold, risk_axes, specialist_reports, prior_findings, mode, model, build_cmd, test_cmd` ไม่มีค่า → `(none)`

dispatch prompt ≤ 200 คำ: บทบาท, input paths, output (artifact + out.json + `{{hs}} validate`), ข้อห้าม 2–3 ข้อ ความรู้วิธีทำงานอยู่ใน agent .md

### 9.2 Agent files

| agent | model | tools | ขอบเขต |
|---|---|---|---|
| architecter | opus | Read, Grep, Glob, Write | เขียนเฉพาะ phase dir; design ตาม template; out.json §6.1; อ่าน wiki ก่อน |
| implementer | sonnet | Read, Write, Edit, Grep, Glob, Bash | แก้เฉพาะ owned; รัน build เอง; ไม่เขียนเทสใหม่; out.json §6.2 |
| tester | sonnet | Read, Write, Edit, Grep, Glob, Bash | แก้เฉพาะ test_owned; เรียก `hs redgreen`; ไม่แตะ production; out.json §6.3 |
| reviewer | opus | Read, Grep, Glob, Bash, Write | อ่าน diff เอง เสมอ; เขียนเฉพาะ phase dir; verify ต่อ finding; `prior_id`; delta mode; out.json §6.4 |
| specialist | opus | Read, Grep, Glob, Bash, Write | axis เดียวตาม `references/axis-<axis>.md`; out.json |
| product | opus | Read, Grep, Glob, Write | brainstorm เท่านั้น |

ตัด: brainstorm mode, token discipline, marker format, ตารางที่ hs parse แทน คงไว้: กฎคุณภาพที่เป็นวิจารณญาณ (round-trip over hardcoded, chief reads the diff, mocked DB ไม่นับ, scale จาก design, wiki lessons = blocker) ใน P2 PR เดียวกัน ย้าย brainstorm text ไป `prompts/brainstorm/*.md` และชี้ brainstorm skill (0.16) ไปที่นั่น ไม่งั้น `/brainstorm` พัง

### 9.3 `feedback.md` (hs เขียน)

```
# Feedback for iteration <N+1>  (target: implementer | workstream: backend)
## Blockers
| id | tag | file:line | desc | verify |
## Majors (fix if cheap)
## Failing verify (inner pass ≥ 2)
## Gate failure (ถ้ามี)
## Reviewer summary
```

## 10. Orchestrator skill (`skills/squad-loop/SKILL.md`, ≤ 400 คำ)

1. `hs run start "<task>" <flags>` (หรือ `hs resume`) อ่าน action
2. ทำตาม action:
   - `dispatch` / `dispatch_many`: Agent tool (`subagent_type: happysquad:<agent>`, `model`, prompt = เนื้อหา `prompt_file`, cwd ถ้ามี) ทั้ง wave ในข้อความเดียว
   - `wait`: Bash `hs wait --timeout 540` (foreground, timeout 600000) อ่าน action ที่คืนมา ถ้าได้ `wait` อีก เรียกซ้ำ
   - `ask`: AskUserQuestion → `hs answer <key> <value>` → `hs next`
   - `done`: รายงาน ≤ 150 คำจาก field ของ action; `wiki_offer` → ถาม 1 ครั้ง
3. หลัง Agent tool คืนผล: `hs advance` → กลับข้อ 2

กฎ: ไม่อ่าน design/review/evidence เอง; ไม่แก้ state; Agent error → retry 1 ครั้ง, ครั้งที่ 2 `hs block --cause agent`; ไม่จบ turn ขณะมี dispatch ค้าง; ไม่มี `until`/`sleep` loop ใน skill

## 11. Drivers

`config.driver` หรือ `--driver`:

- **`agent-tool`** (default): orchestrator LLM ตาม §10
- **`headless`**: hs วน loop เอง ทุก dispatch = subprocess:
  ```
  HS_CHILD=1 claude -p "$(cat <prompt_file>)" \
    --agents '<json ที่ render จาก agents/<agent>.md: name, description, prompt, model, tools>' --agent <agent> \
    --model <m> --permission-mode acceptEdits \
    --allowedTools "<config.headless.allowed_tools>" \
    --disallowedTools "<config.headless.disallowed_tools>" \
    --max-budget-usd <config.headless.budget_per_phase>
  ```
  `--agents`/`--agent` ทำให้ frontmatter `tools` ถูกบังคับ ไม่ใช้ `--append-system-prompt-file` ไม่ใช้ `--bare` (ตัด OAuth/keychain) `HS_CHILD=1` ทำให้ hook ของ plugin เงียบใน child wave = subprocess พร้อมกัน ≤ `max_parallel` ใช้สำหรับ overnight, CI, fleet children

  **Isolation (Q2 ปิดแล้ว: isolated worktree เป็น default).** `headless.isolate` default `"worktree"`: `hs run start --driver headless` สร้าง `git worktree add -b hs/<run-id> <git-common-dir>/happysquad/wt/<run-id> HEAD` แล้วรัน run ทั้งหมดในนั้น (`state.worktree` set, `.happysquad/` ของ worktree เป็นของ run นี้) เมื่อ COMPLETE: `done` action มี `branch: "hs/<run-id>"` และ `suggested_merge` ไม่ auto-merge BLOCKED: worktree คงไว้ให้ inspect `headless.isolate: "none"` ต้องตั้งเองเพื่อรันบน working tree จริง deny-list เป็นชั้นเสริมเสมอ ไม่ใช่กำแพง (ตรง prefix เท่านั้น, `sh -c "git push"` ผ่าน, snapshot ไม่เห็น `.env`) worktree แบบนี้ใช้กลไกเดียวกับ fleet child (§12) จึงไม่เพิ่มโค้ด P4 มาก
- **`fake`**: = headless ที่ `HS_CLAUDE=evals/fake_agent.py` fake binary รับ argv เดียวกัน (จึงเทส argv construction รวม deny-list ได้ที่ $0) เขียน out.json + artifacts ตาม `--scenario`

## 12. Fleet (P4)

- `hs fleet start <tasks-file> [--max N]`: สร้าง worktree `fleet/<fleet-id>/<slug>` จาก base branch (`--frontier`, `--drain`, `squad:passed` → 1.1)
- children รัน `hs run start --driver headless` ใน worktree parent poll `<wt>/.happysquad/runs/<id>/state.json`
- `hs fleet advance`: reconcile (COMPLETE/BLOCKED/quiet 30 นาที → `stalled`), dispatch pending จนครบ `max_parallel`
- `aggregate-report.md` + merge commands ไม่ auto-merge ไม่ลบ worktree เว้นแต่ `--cleanup`
- `skills/fleet/SKILL.md` ≤ 300 คำ

**fleet-status ต่อ phase:** P0–P3 ใช้ `/squad-fleet` ของ 0.16 ต่อ (mark "unsupported on the new loop"); P4 แทนที่

## 13. Brainstorm, stack-detector, dev-wiki

- **brainstorm**: orchestration แบบ 0.16 (marker + session.json ที่ skill เขียน) คงไว้ใน v1.0 แค่ย้าย round instructions ไป `prompts/brainstorm/*.md` (P2) `hs brainstorm` → 1.1
- **stack-detector**: เหมือนเดิม + seed `config.build_cmd` / `test_cmd` / `coverage_report` ให้ `hs init` mapping ตารางในตัวไปก่อน (`skill-map.json` → 1.1)
- **dev-wiki**: เหมือนเดิม (`hs wiki lint` → 1.1)

## 14. Commands

| command | ทำอะไร |
|---|---|
| `/happysquad-loop <task> [--lite\|--full] [--no-parallel] [--driver X]` | §10 |
| `/squad-architect <task>` | `hs run start` + ARCHITECT เท่านั้น แล้วหยุด |
| `/squad-review [--base <ref>]` | run แบบ review-only: base_ref = merge-base → gate test → RISK → SPECIALISTS → REVIEW |
| `/squad-status` | `hs status` |
| `/squad-resume` | `hs resume` + §10 |
| `/squad-fleet <file> [--max N]` | §12 (P4; ก่อนนั้นคือ 0.16) |
| `/squad-detect` | stack-detector |
| `/brainstorm <topic> [--rounds=2] [--quick]` | §13 |
| `/wiki-ingest`, `/wiki-ask`, `/wiki-lint` | เดิม |

ตัดใน P3: `/squad-implement`, `/squad-test`, `/squad-assemble`, `/ask-kilo` **กฎ:** command ถูกลบใน phase เดียวกับที่ตัวแทนมา `/squad-drain`: ดู Q6 §20

## 15. Hooks

```json
{"hooks":{
  "SessionStart":[{"hooks":[{"type":"command","command":"python3 \"${CLAUDE_PLUGIN_ROOT}/bin/hs\" hook session-start"}]}],
  "Stop":[{"hooks":[{"type":"command","command":"python3 \"${CLAUDE_PLUGIN_ROOT}/bin/hs\" hook stop"}]}]}}
```

- `HS_CHILD=1` → exit 0 เงียบทันที
- `session-start`: ไม่มี `.happysquad/` → เงียบ; มี → เขียน `.happysquad/.session`, resume nudge ≤ 5 บรรทัดเมื่อมีงานค้าง, DRIFT warning; ไม่พิมพ์ git log
- `stop`: เฉพาะ `config.hooks.stop_progress_nudge=true`
- exit 0 เสมอ ยกเว้น nudge exit 2 ห้ามใช้ `rtk`

## 16. Config

### 16.1 Schema + defaults (ฝังใน hs; `hs config` พิมพ์ effective)

```json
{"driver":"agent-tool","interactive":true,
 "cap":5,"inner_cap":2,"gate_retries":1,"validation_retries":2,"gate_timeout":600,
 "coverage_threshold":80,"review_mode":"split-on-risk",
 "max_parallel":4,
 "models":{"architecter":"opus","implementer":"sonnet","tester":"sonnet","reviewer":"opus","specialist":"opus","product":"opus"},
 "lite":{"auto":true,"cap":3},
 "build_cmd":null,"test_cmd":null,"coverage_report":null,
 "allowed_flags":["--run","--filter","--grep","-t","-k","--testNamePattern","--coverage"],
 "generated":["**/pnpm-lock.yaml","**/package-lock.json","**/yarn.lock","**/__snapshots__/**"],
 "headless":{"budget_per_phase":2.0,
   "allowed_tools":"Read,Write,Edit,Grep,Glob,Bash",
   "disallowed_tools":["Bash(git push:*)","Bash(git reset:*)","Bash(git clean:*)","Bash(git checkout:*)","Bash(git commit:*)","Bash(rm -rf:*)","Bash(curl:*)","Bash(wget:*)","Bash(sudo:*)","Bash(gh:*)"],
   "isolate":"worktree"},
 "hooks":{"stop_progress_nudge":false},
 "wiki":{"offer":true},
 "fleet":{"base_branch":null}}
```

`coverage_threshold: null` = ไม่ gate coverage `headless.isolate` ∈ {`worktree`, `none`} key ที่ไม่รู้จัก → warning ครั้งเดียว

### 16.2 Non-interactive defaults (`interactive=false`)

| key | default |
|---|---|
| `resume_existing` | resume |
| `stack_profile_stale` | refresh |
| `claude_md_missing` | skip |
| `dirty_tree` | proceed (snapshot เป็น base_ref) |
| `test_cmd_missing` | BLOCKED cause=config (ก่อน ARCHITECT) |
| `wiki_offer` | no |
| `brainstorm_proceed` | stop |
| `fleet_cleanup` | keep |
| `fleet_wiki_ingest` | no |

## 17. Git hygiene

- `hs init` เขียน `.happysquad/.gitignore`: `*`, `!.gitignore`, `!config.json`, `!stack-profile.md`, `!stack-profile.json`, `!risk-patterns.json` ไม่แตะ root `.gitignore`
- ทุก diff ใน hs: `-- . ':(exclude).happysquad' ':(exclude)knowledge'` + untracked ผ่าน `git ls-files --others --exclude-standard`
- `hs snapshot`: temp index **copy จาก index จริง** (`shutil.copy .git/index`) ใต้ `<git-common-dir>/happysquad/tmp/`, `git add -A`, `write-tree`, `commit-tree -p HEAD`, แล้ว **pin** เป็น `refs/happysquad/<run>/base` หรือ `refs/happysquad/<run>/iter-<N>` ลบ ref ทั้งหมดของ run เมื่อ COMPLETE (BLOCKED คงไว้ให้ inspect) repo ไม่มี commit → `base_ref=null`, redgreen = not-runnable snapshot ไม่เห็นไฟล์ที่ gitignore (เช่น `.env`) จึงป้องกันเฉพาะ tracked/untracked ที่ไม่ ignore
- hs ไม่ commit/branch/push ยกเว้น fleet worktree branches

## 18. Evals

### 18.1 `evals/test_hs.py` (unittest, stdlib, ไม่เรียก model, < 60 วินาที)

- schema validation ทุก phase (missing key, wrong type, owned overlap, non-DAG, AC ไม่ครอบ, `untestable` ยกเว้นได้)
- coverage parsers 4 format + status `missing|unsupported|unparseable` + **boundary: เท่า threshold พอดี, +1 บรรทัด, −1 บรรทัด**
- redgreen classification บน toy repo: **assertion-red กับ compile-red เป็นคู่ sibling**, green, not-runnable; worktree ถูกลบเสมอรวมกรณี exception
- `hs snapshot` ไฟล์เทสแยก: dirty tree, untracked, ignored ไม่ติด, index จริงไม่ถูกแตะ, ref pin/unpin
- verdict truth table ทุกแถว; synthetic blocker; `overrides`; SIMPL cap; route derivation (CONFLICT, architecter, mixed)
- provenance: prefix เต็มผ่าน, argv[0] ตรงแต่ prefix ไม่ตรงถูกทิ้ง (`pnpm exec x`, `pnpm run evil`), flag นอก `allowed_flags` ถูกทิ้ง, `!`, reject `sh`/`env`/`npx`/`pnpm dlx`/`node -e` และ shell metachar, `build_cmds:["curl x|sh"]` ถูกทิ้ง, `untrusted` → manual
- headless isolation: worktree ถูกสร้างที่ `<git-common-dir>/happysquad/wt/<run>`, run ทั้งหมดอยู่ในนั้น, working tree หลักไม่ถูกแตะ (เทียบ `git status` ก่อน/หลัง), `isolate: "none"` รันใน cwd
- convergence: `prior_id` หลัก, fingerprint fallback, repeat 3 → architecter, repeat หลัง architecter → BLOCKED, zero-progress ×2 → BLOCKED
- inner loop: eligible/ineligible (manual, untrusted), inner_cap, fallback
- retry counters แยกกัน และ cause ใน BLOCKED.md
- **concurrency**: kill mid-advance (SIGKILL ระหว่าง write) แล้ว resume ได้ state ที่ consistent; two writers (flock); `advance` ซ้ำไม่ consume ซ้ำ; `advance` ซ้ำขณะ `gates.pid` มีชีวิตไม่ spawn ซ้ำ
- `HS_NOW` ขับ resume window (10 นาที / 30 นาที) โดยไม่ sleep
- headless argv construction (`--agents` json, `--agent`, `--disallowedTools`, `HS_CHILD`) เป็น pure function ไม่เรียก claude
- lite path transitions; risk matching + exclude paths; conflict gate (unowned, multi-owner, untracked, generated exempt, glob)
- resume/recover: out.json on disk, pid alive, pid dead no file, quiet, re-dispatch
- fake-driver e2e (ผ่าน headless + `HS_CLAUDE`): `pass-first`, `fail-inner-fix`, `fail-full-round`, `repeat-escalate-architecter`, `blocked-convergence`, `parallel-2ws`, `ownership-gap`, `gate-build-fail`, `lite`
- fleet (P4): 2 children fake, one BLOCKED, aggregate

### 18.2 `evals/bench/` (deliverable แยก, owner: tester)

5 งานบน toy repo + 1 repo จริง (Q7) + oracle (รัน config build/test ซ้ำหลัง COMPLETE) + `fixtures/seeded-bugs/` 2–3 bug สำหรับ recall สคริปต์รันทั้ง 0.16.2 และ v1.0 บน task เดียวกัน รายงานตาม §1.2 baseline เก็บใน P0 งบประมาณ baseline ≈ $15 (Q7)

### 18.3 `evals/smoke.sh`

toy repo + `claude -p` headless driver 1 loop, `--max-budget-usd 3`, gate ที่ใช้เวลา > 120s หนึ่งอัน, assert `COMPLETE` + coverage ≥ 80 รันก่อน tag ทุกครั้ง จับ CLI flag drift ที่ fake จับไม่ได้

### 18.4 CI

`python3 -m unittest discover -s evals` บน push; smoke และ bench manual

## 19. แผนงานและ acceptance criteria

| phase | งาน | exit criteria |
|---|---|---|
| **P0 spike (1 วัน)** | hs ขั้นต่ำ (ARCHITECT → IMPLEMENT → COMPLETE, flock, `hs wait`) + skill 3 ขั้น; รัน `claude -p` บน toy repo ที่มี gate > 120s; สัปดาห์เดียวกัน: เก็บ baseline 0.16.2 บน bench (§18.2) | ≥ 10 dispatch ต่อเนื่องโดยไม่ช่วยมือ; baseline ครบ 7 metric; ตอบได้ว่า driver + detached gate ใช้ได้จริง ถ้าไม่ผ่าน → หยุดและทบทวน driver ก่อนทำ P1 |
| **P1a hs core (size M)** | package `hs/` ตาม §3: config, state (ยังไม่ flock), schemas + `hs validate`, machine (transitions, verdict truth table — Q1 ปิดแล้ว, convergence, iteration table), coverage parsers, redgreen, snapshot/refs, render, risk, conflict, resume; gates รัน **foreground** ไปก่อน; provenance แบบ prefix เต็ม (§7.0) ตั้งแต่แรก เพราะเป็น input ของ gates; `fake_agent.py` + 9 scenarios; `test_hs.py` ทุกหัวข้อ §18.1 ยกเว้น concurrency และ detached gates | `test_hs.py` ผ่าน; fake e2e ผ่านทุก scenario; `hs` ใช้กับ toy repo ด้วยมือได้ครบ loop; skill 0.16 ยังใช้ได้ (ไม่แตะ) **ส่งมอบของที่ใช้ได้ก่อน hardening** |
| **P1b hardening (size M)** | flock + atomic write + event-before-state + re-entrant consume; `hs _gates` detached + `hs wait` + pid tracking; `os.killpg`; `HS_NOW`; `git worktree prune` + tmp sweep; headless worktree isolation (§11); concurrency tests (kill-mid-advance, two writers, duplicate `_gates`) | concurrency tests ผ่าน; `hs wait --timeout 540` คืน action ถูกต้องเมื่อ gate > 540s; P0 spike ซ้ำด้วย P1b ผ่าน 10 dispatch |
| **P2 driver + agents** | squad-loop SKILL.md ใหม่; 6 agent files; prompts/ รวม brainstorm/ (ชี้ brainstorm skill ไปด้วย); headless driver; smoke; seeded-bug fixture; bench run v1.0 | **dogfood gate** บน 5 งาน bench: 0 false COMPLETE; **0 manual resumes or state edits**; 0 destructive actions; BLOCKED ≤ baseline; recall ≥ baseline; แสดง $/COMPLETE เทียบ baseline; smoke COMPLETE; word budgets §9.2 |
| **P3 cuts + ops** | เริ่มได้เมื่อ P2 gate ผ่านเท่านั้น; ย้าย §2.1 ไป `happysquad-ext` แล้วลบ; hooks ใหม่; non-interactive; lite; `.gitignore`; README/CHANGELOG; ลบ command เฉพาะที่ตัวแทนมาแล้ว; `/squad-fleet` 0.16 คงไว้ mark unsupported; tag v1.0.0-rc1 | ไม่มี AskUserQuestion เมื่อ `interactive=false` (fake + headless); `--lite` บน bug 1 ไฟล์ ≤ 4 dispatch; ทุก command ใน §14 ใช้ได้ |
| **P4 fleet** | `hs fleet start|advance`, headless children, `--cleanup`; fleet fake e2e; tag v1.0.0 (หรือก่อน P4 ตาม Q6) | fleet fake e2e ผ่าน; `/squad-fleet` ใหม่แทน 0.16 |

## 20. การตัดสินใจและคำถามเปิด

### ตัดสินใจแล้ว (พี่จี, 2026-10-02)

- specialist dispatch ก่อน chief (ไม่ parallel)
- reviewer ไม่ส่ง verdict, hs คำนวณจาก truth table
- ownership overlap ไม่มี worktree fallback
- team-assembly / external executors / ask-kilo / fable escalation → `happysquad-ext`
- รับ dissent ของ product: P2 gate นับ "manual resumes or state edits" → brainstorm เป็น full-consensus
- python3 เป็น hard dependency; run เก่าจาก 0.16 ใช้กับ v1.0 ไม่ได้
- **Q1 ปิด:** refactor/config/docs ที่ไม่มี failing-first test COMPLETE ได้ TEST major ถูก inject และ reviewer ยกเป็น blocker ได้เมื่อ diff เปลี่ยน behaviour (§6.3, §6.4) verdict function เขียนได้ใน P1a
- **Q2 ปิด:** headless ใช้ isolated worktree เป็น default (`headless.isolate: "worktree"`) deny-list เป็นชั้นเสริม (§11, §16.1)
- **Provenance ใช้ prefix เต็ม** ไม่ใช่ argv[0] (§7.0) ยอมให้ `verify` ตกเป็น `manual` มากขึ้น
- **P1 แยกเป็น P1a (core, foreground gates, ใช้ได้จริง) และ P1b (hardening: locking, detached gates, isolation)** (§19)
- **hs เป็น package `hs/` หลายไฟล์** `bin/hs` เป็น entry (§3, §4)

### คำถามเปิด (จาก consensus)

| # | คำถาม | block อะไร |
|---|---|---|
| Q3 | v1.0 ผูกกับวันหรือ scope อะไรยอมได้ | ขนาด P1a/P1b |
| Q4 | repo เป้าหมายใช้ coverage format และรูปแบบ repo แบบไหน (monorepo, Go, JVM) ใน `workspace:*` repo green ที่ ref ควรนับ `not-runnable` หรือยอมรับความเสี่ยง | parser scope, redgreen rule |
| Q5 | มีคนอื่นใช้ plugin ไหม (migration note, Windows) glm/opencode offload ประหยัดจริงไหมวันนี้ | P3 docs |
| Q6 | tag v1.0.0 ต้องรอ fleet (P4) หรือ ship หลัง P3 ได้ `/squad-drain` คงเวอร์ชัน 0.16 ถึง 1.1 หรือตัดโดยไม่มีตัวแทน | P3/P4 |
| ~~Q7~~ | **ปิด (2026-10-03):** bench ใช้ happysquad repo เอง 5 งานบน `hs/` ใน `evals/bench/tasks.md`; coverage ผ่าน `evals/cov.py` (stdlib `trace` → lcov) เพราะไม่มี `coverage` module; threshold 50 | – |
