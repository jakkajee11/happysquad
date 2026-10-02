# happysquad v1.0 — rewrite spec

Status: DRAFT (2026-10-02) · Owner: พี่จี · Baseline: happysquad 0.16.2

## 0. ทำไมต้องรื้อ

0.16.2 ให้ orchestrator ที่เป็น LLM อ่าน prose 7,000 คำแล้วทำงาน deterministic เองทุกรอบ (อัปเดต state, รัน gate, parse marker, regex risk, convergence) ผลคือทำพลาดได้ทุกรอบ กิน context ก่อนเริ่มงาน เทสไม่ได้ และทุก release แก้ wait/recover logic โดยไม่มี regression test

หลักเดียวของ v1.0: **LLM ทำเฉพาะงานที่ต้องใช้วิจารณญาณ (ออกแบบ เขียนโค้ด เขียนเทส รีวิว) กลไกทั้งหมดเป็นโค้ดที่เทสได้โดยไม่เรียก model**

สิ่งที่คงไว้จาก 0.16: artifact hand-off, marker เป็น claim, evidence gate, red→green proof, Verify ต่อ finding, inner fix loop + delta review, convergence detection, split-on-risk, wiki read-back, fleet ใน worktree, brainstorm 3 รอบ, cross-session resume

## 1. เป้าหมายและตัวชี้วัด

| เป้าหมาย | วัดจาก | 0.16.2 | v1.0 |
|---|---|---|---|
| orchestrator ไม่ต้องอ่าน artifact | ขนาด `squad-loop/SKILL.md` | 7,087 คำ | ≤ 400 คำ |
| state เขียนโดยโค้ดเท่านั้น | จุดที่ LLM เขียน `state.json` | ทุก transition | 0 |
| evidence ไม่ผ่านมือ LLM | ที่มาของ coverage / red-green | agent พิมพ์ | script เขียน |
| เทสได้โดยไม่เรียก model | logic ที่มี unit test | 0 | gates, transitions, convergence, risk, resume |
| รัน autonomous ได้ | AskUserQuestion ใน loop path เมื่อ `interactive=false` | 6+ | 0 |
| งานเล็กจ่ายน้อย | phase ของ bug fix 3 บรรทัด | เท่า feature | lite path |
| prompt ต่อ dispatch | reviewer agent | 3,260 คำ | ≤ 900 คำ |

## 2. Non-goals (ตัดทิ้ง)

ตัดออกจาก core ทั้งหมด **ตัดสินใจแล้ว (2026-10-02):** ย้ายไฟล์ไป repo `happysquad-ext` (plugin แยก ยังไม่ต้องใช้ได้ใน v1.0) ก่อนลบจาก repo นี้ใน P3

- External executors (glm/opencode), tmux pane rule, quota fallback, mechanical offload (§11 เดิม)
- `/squad-assemble` + team-assembly skill
- `/ask-kilo` + ask-kilo skill
- Fable-specific escalation (§10a) → แทนด้วย `escalation.model` ทั่วไป (§8.6)
- Worktree-per-workstream fallback + merge ด้วย `git diff | git apply` (§8 เดิม)
- `/squad-implement`, `/squad-test` (manual mid-loop step ที่ข้าม gate)
- `/squad-drain` → เป็น `/squad-fleet --drain`
- requirement-reviewer, standard-reviewer (default mode ไม่เคย dispatch)
- "Brainstorm mode" ในทุก agent file → ย้ายไป brainstorm skill
- Git snapshot ใน SessionStart hook (ซ้ำกับ context ที่ Claude Code ใส่ให้)
- Hardcoded skill registry ใน stack-detector → ย้ายไปไฟล์ที่ user override ได้

## 3. โครงสร้างไฟล์

```
happysquad/
├── .claude-plugin/plugin.json          # description ประโยคเดียว
├── bin/hs                              # python3 stdlib, executable, ไฟล์เดียว
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
│   ├── axis-sec.md  axis-perf.md       # checklist ต่อแกน
│   ├── risk-patterns.json              # default risk regex
│   ├── skill-map.json                  # default signal→skill mapping
│   └── design-template.md  design-template-lite.md
├── skills/
│   ├── squad-loop/SKILL.md             # driver 3 ขั้น
│   ├── fleet/SKILL.md
│   ├── brainstorm/SKILL.md
│   ├── stack-detector/SKILL.md
│   └── dev-wiki/SKILL.md (+ references/ เดิม)
├── commands/                           # 11 ไฟล์ (§14)
├── hooks/hooks.json                    # เรียก hs hook ...
├── evals/
│   ├── test_hs.py                      # unittest, ไม่เรียก model
│   ├── fake_agent.py                   # fake driver
│   ├── fixtures/toy-repo/              # zero-dep node, node --test + lcov
│   ├── fixtures/coverage/              # lcov.info, cobertura.xml, coverage-summary.json, coverage.json
│   ├── scenarios/*.json                # fake-driver scenarios
│   └── smoke.sh                        # claude -p จริง 1 loop, budget cap
├── docs/spec/v1-rewrite.md             # ไฟล์นี้
├── CHANGELOG.md
└── README.md
```

Run directory ที่ `hs` สร้าง:

```
.happysquad/
├── .gitignore                          # hs init เขียน (§17)
├── config.json                         # user
├── stack-profile.{md,json}
├── risk-patterns.json                  # optional override
├── state.json                          # hs เท่านั้น
├── runs/<run-id>/
│   ├── events.jsonl                    # append-only
│   ├── task.md
│   ├── design.md
│   ├── prompts/<PHASE>-i<N>[-<ws>].md  # rendered dispatch prompts
│   ├── <PHASE>-i<N>[-<ws>]/            # phase dir
│   │   ├── out.json                    # agent เขียน
│   │   ├── *.md                        # artifact ของ phase (implementation.md, test-report.md, review.md)
│   │   ├── gate-build.json / gate-test.json / redgreen.json / verify.json
│   │   └── logs/*.log
│   ├── conflict.json  risk.json
│   ├── feedback.md
│   ├── BLOCKED.md
│   └── HANDOFF.md
├── fleets/<fleet-id>/{fleet.json,tasks.md,aggregate-report.md}
├── worktrees/<fleet-id>/<slug>/
├── brainstorms/<session-id>/
└── tmp/                                # red-green worktrees
```

## 4. `hs` CLI contract

python3 ≥ 3.9 stdlib เท่านั้น ทุกคำสั่งพิมพ์ JSON บรรทัดเดียวบน stdout เว้นแต่ระบุ exit 0 = สำเร็จ, 1 = gate/validation fail (เป็นผลลัพธ์ปกติ), 2 = usage/IO error ทุกคำสั่งรับ `--run <id>` (default: `state.json.run_id`) และ `--json`/`--brief`

| คำสั่ง | ทำอะไร | เขียนอะไร |
|---|---|---|
| `hs init [--non-interactive]` | สร้าง `.happysquad/`, `.gitignore`, `config.json` default ถ้าไม่มี | `.happysquad/*` |
| `hs config` | พิมพ์ effective config (default + file) | – |
| `hs run start "<task>" [--lite\|--full] [--no-parallel] [--driver X]` | สร้าง run, snapshot base_ref, state=ARCHITECT, คืน action แรก | state, events, task.md |
| `hs next` | idempotent: action ถัดไปตาม state ไม่เปลี่ยน state | prompts/ (render) |
| `hs advance` | consume out.json ที่ค้าง → validate → gates → transition → คืน action ถัดไป | state, events, gate files, feedback.md |
| `hs gate build\|test\|conflict [--phase-dir D]` | รัน gate เดี่ยว (advance เรียกเอง; tester/reviewer เรียกมือได้) | gate-*.json |
| `hs redgreen --ref R --tests F... [--cmd C] [--copy P...]` | red proof ใน throwaway worktree | redgreen.json |
| `hs verify <review.json>` | รัน Verify command ทุก finding | verify.json |
| `hs risk` | regex บน diff vs base_ref | risk.json |
| `hs snapshot` | dangling commit ของ working tree (base_ref / iter_ref) | พิมพ์ sha |
| `hs status [--brief]` | สรุป run/fleet/brainstorm ≤ 40 บรรทัด | – |
| `hs resume` | หา candidate ที่ค้าง, recover จาก out.json บนดิสก์, คืน action | state, events |
| `hs block "<reason>"` | บังคับ BLOCKED (ใช้โดย driver เมื่อ agent ตาย 2 ครั้ง) | BLOCKED.md |
| `hs fleet start <tasks-file\|--frontier> [--max N] [--drain]` | สร้าง worktrees, fleet.json | fleets/, worktrees/ |
| `hs fleet advance` | reconcile children, คืน children ที่ต้อง dispatch/wait | fleet.json |
| `hs frontier` | อ่าน tracker frontier (local md / gh / glab) | – |
| `hs wiki lint` | deterministic lint ของ dev-wiki (index, links, raw refs) | knowledge/wiki |
| `hs hook session-start\|stop` | hook bodies | `.happysquad/.session` |

### 4.1 Action schema (ผลลัพธ์ของ `run start` / `next` / `advance` / `resume`)

```json
{"action":"dispatch","phase":"ARCHITECT","iteration":1,"agent":"architecter","model":"opus",
 "prompt_file":".happysquad/runs/R/prompts/ARCHITECT-i1.md",
 "out_file":".happysquad/runs/R/ARCHITECT-i1/out.json","workstream":null,"cwd":null}

{"action":"dispatch_many","phase":"IMPLEMENT","wave":1,"dispatches":[{...},{...}]}

{"action":"wait","out_files":["..."],"since":"2026-10-02T10:00:00Z"}

{"action":"ask","key":"resume_existing","question":"...","options":["resume","restart","new"],"default":"resume"}

{"action":"done","status":"COMPLETE|BLOCKED","run_id":"R","iterations":2,
 "files_changed":12,"coverage":84.2,"report":".happysquad/runs/R/REVIEW-i2/review.md",
 "suggested_commit":"feat: ...","wiki_offer":true}
```

`ask` ออกเฉพาะ `interactive=true` ถ้า `false` hs ใช้ default ตาม §16.2 แล้วเดินต่อเอง orchestrator ตอบ `ask` ด้วย `hs answer <key> <value>` แล้วเรียก `next` ใหม่

## 5. State model

### 5.1 `state.json` (hs เขียนเท่านั้น)

```json
{"run_id":"20261002-101500-add-api-key-auth","task":"...","driver":"agent-tool",
 "mode":"single|parallel","lite":false,"size":"M",
 "base_ref":"<sha>","iter_ref":null,
 "state":"IMPLEMENT","iteration":1,"inner_pass":0,"gate_retry":0,"escalated":false,
 "cap":5,"inner_cap":2,"coverage_threshold":80,"review_mode":"split-on-risk",
 "workstreams":[{"name":"backend","owned":["..."],"depends_on":[],"ac":["AC-1"],
                 "impl":"pending|dispatched|done","test":"pending|dispatched|done"}],
 "pending":[{"phase":"IMPLEMENT","iteration":1,"workstream":"backend",
             "out_file":"...","dispatched_at":"..."}],
 "fingerprints":{"<fp>":{"id":"R-1","seen":[1,2],"routes":["implementer","implementer"]}},
 "parent_fleet_id":null,"worktree":null,
 "started_at":"...","updated_at":"..."}
```

`pending` คือรายการ dispatch ที่ยังไม่ consume `advance` ทำงานกับรายการนี้เท่านั้น

### 5.2 `events.jsonl` (append-only)

หนึ่งบรรทัดต่อเหตุการณ์ `{"ts","event","phase","iteration","workstream","data"}` events: `run.start`, `dispatch`, `consume`, `gate.build`, `gate.test`, `gate.conflict`, `risk`, `verify`, `transition`, `review`, `convergence`, `escalate`, `ask`, `answer`, `block`, `complete`, `resume`, `recover` status, resume และ hook อ่านจากไฟล์นี้ ไม่มี `history` array ใน state.json

### 5.3 Phase directory

`<PHASE>-i<N>[-<ws>]/` phase ซ้ำใน iteration เดียวกัน (gate retry) ใช้ suffix `-r1`, `-r2` ไม่ลบของเก่า

## 6. Phase output contracts (`out.json`)

ทุก agent จบงานด้วยการเขียน `out.json` ที่ `{{out_file}}` ไม่มี marker บรรทัดข้อความอีกต่อไป final message ของ agent เป็นอะไรก็ได้ orchestrator ไม่ parse

`hs advance` validate ด้วย schema ฝังในตัว key ขาด/ผิด type → `{"action":"dispatch", ..., "retry_reason":"out.json missing key: workstreams"}` re-dispatch phase เดิมหนึ่งครั้ง (`gate_retry`) ครั้งที่สอง → BLOCKED

### 6.1 ARCHITECT

```json
{"phase":"ARCHITECT","size":"S|M|L","design":"design.md",
 "assumptions":["..."],
 "ac":[{"id":"AC-1","text":"accepts valid API key, returns 200"}],
 "workstreams":[{"name":"backend","owned":["src/auth.ts","src/routes.ts"],"depends_on":[],"ac":["AC-1","AC-2"]}],
 "test_owned":{"backend":["tests/auth.test.ts"]},
 "shared_read_only":["src/db.ts"]}
```

กฎที่ hs ตรวจ: `owned` ข้าม workstream ต้องไม่ซ้ำ (ซ้ำ → re-dispatch พร้อมเหตุผล ไม่มี worktree fallback), `depends_on` ต้องเป็น DAG, ทุก AC ต้องอยู่ใน workstream ใดสักอัน, ทุกไฟล์ที่กล่าวถึงใน design.md ด้วย pattern `` `path/with/ext` `` ที่ไม่มีอยู่ใน repo ต้องอยู่ใน `owned` (แทน ownership self-check แบบ prose) `size=S` + `lite.auto=true` → run เข้า lite path (§8.5)

### 6.2 IMPLEMENT (ต่อ workstream)

```json
{"phase":"IMPLEMENT","workstream":"backend",
 "files":["src/auth.ts"],
 "build_cmds":["pnpm build","pnpm lint"],
 "unmet_ac":[{"id":"AC-3","reason":"..."}],
 "design_conflict":null,
 "ownership_gap":null}
```

`ownership_gap: {"file":"...","reason":"..."}` → hs route ไป ARCHITECT พร้อม feedback (ไม่นับ iteration ใหม่ถ้าเป็น gap แรกของ run, นับถ้าซ้ำ) `design_conflict: "<text>"` → เหมือนกัน hs ตรวจว่า `files` ⊆ `owned` และ `git diff --name-only base_ref` ของ workstream ⊆ `owned` ด้วย (เฉพาะ single run ตรวจทันที; parallel ตรวจที่ conflict gate)

### 6.3 TEST (ต่อ workstream)

```json
{"phase":"TEST","workstream":"backend",
 "test_cmds":["pnpm test -- --coverage"],
 "coverage_report":"coverage/lcov.info",
 "test_files":["tests/auth.test.ts"],
 "new_tests":["tests/auth.test.ts"],
 "ac_map":{"AC-1":["tests/auth.test.ts::rejects expired key"]},
 "redgreen":"redgreen.json",
 "findings":[{"ac":"AC-2","desc":"impl returns 500 not 401"}]}
```

tester **ต้อง** เรียก `hs redgreen --ref {{proof_ref}} --tests <new_tests>` เอง (hs ทำ worktree ให้ทั้งหมด) `redgreen.json` ต้องมีอยู่และ `ac_map` ต้องครอบคลุมทุก AC ของ workstream ไม่งั้น validation fail

### 6.4 REVIEW (chief) และ SPECIALIST

```json
{"phase":"REVIEW","mode":"single|split-on-risk|delta",
 "report":"review.md",
 "findings":[
  {"id":"R-1","severity":"blocker|major|minor","tag":"REQ|SEC|PERF|STD|SIMPL|TEST|CONFLICT",
   "file":"src/auth.ts","line":42,"desc":"API key compared with == not const-time",
   "route":"implementer|tester|architecter","workstream":"backend",
   "verify":"! grep -qE 'apiKey\\s*==' src/auth.ts","source":"self|sec|perf"}],
 "axes":{"REQ":"PASS","SEC":"FAIL","PERF":"PASS","STD":"PASS","SIMPL":"PASS","TEST":"PASS"},
 "confirmed_fixes":["R-1"]}
```

**reviewer ไม่ส่ง verdict** hs คำนวณ: `verdict = no blocker ∧ verified_coverage ≥ threshold ∧ redgreen ok` route: มี CONFLICT → architecter; มี blocker route=architecter → architecter; ไม่งั้น set ของ route ใน blockers (implementer และ/หรือ tester) `SIMPL` severity ถูกบังคับ ≤ major reviewer ควรรัน `hs verify --dry <out.json>` ก่อนส่งเพื่อยืนยันว่า verify command parse ได้

SPECIALIST: `{"phase":"SPECIALIST","axis":"sec|perf","report":"sec.md","findings":[...]}` ไม่มี `route`/`verify` chief เป็นคนเติม

## 7. Gates (ทั้งหมดใน hs)

### 7.1 `hs gate build`

รัน `build_cmds` ตามลำดับ cwd = repo (หรือ worktree) timeout `gate_timeout` (default 600s) log ไป `logs/build-<n>.log` ผล: `{"ok":true,"cmds":[{"cmd":"pnpm build","exit":0,"log":"..."}]}` fail → feedback.md ส่วน `## Gate failure` (command, exit, log tail 20 บรรทัด) → re-dispatch implementer เดิม (`gate_retry += 1`) เกิน `gate_retries` → BLOCKED

### 7.2 `hs gate test`

1. รัน `test_cmds` เก็บ exit + log
2. อ่าน `coverage_report` รองรับ 4 format ด้วย stdlib: `lcov.info` (LF/LH รวม + ต่อไฟล์), cobertura `*.xml` (`line-rate` ราก + ต่อ class filename), istanbul `coverage-summary.json` (`total.lines.pct` + ต่อไฟล์), pytest-cov `coverage.json` (`totals.percent_covered` + ต่อไฟล์) ไม่พบไฟล์หรือ parse ไม่ได้ → `coverage: null` (= unverified, เป็น TEST finding ให้ reviewer ไม่ใช่ gate fail)
3. per-file coverage ของ `IMPLEMENT.files` ใน workstream
4. ตรวจ `redgreen.json`: ทุกแถวของ `new_tests` ต้องมี, ไม่มี `kind: green`, `ref` ตรงกับ `proof_ref` ที่ hs กำหนด (iter_ref ถ้ามี ไม่งั้น base_ref)
5. ผล `{"ok":bool,"tests":"pass|fail","coverage":84.2,"per_file":{...},"redgreen":{"assertion":3,"compile":2,"not_runnable":0,"all_compile":false}}`

test fail (exit ≠ 0) ไม่ใช่ gate fail ถ้า `TEST.findings` อธิบายไว้ → ส่งต่อ review พร้อม flag reviewer ตัดสิน test fail ที่ไม่มี findings → feedback + re-dispatch tester

### 7.3 `hs redgreen`

```
hs redgreen --ref <sha> --tests tests/a.test.ts tests/b.test.ts \
            [--cmd "pnpm test -- tests/a.test.ts tests/b.test.ts"] \
            [--copy fixtures/x.json] [--link node_modules vendor .env.testing]
```

1. `git worktree add --detach .happysquad/tmp/red-<phase>-<pid> <ref>` (ref null หรือ add fail → ทุกแถว `not-runnable` พร้อมเหตุผล)
2. copy `--tests` + `--copy` ไปที่ path เดียวกัน symlink `--link` (default: `node_modules vendor .venv .env.testing` ถ้ามีในรากของ repo)
3. รัน `--cmd` (default: `config.test_cmd` + test files) ใน worktree, timeout 600s
4. classify ต่อไฟล์เทส: exit 0 → `green`; output match regex compile/import (`Cannot find module|ModuleNotFoundError|cannot find symbol|error TS\d+|SyntaxError|ImportError|undefined reference|package .* is not in`) → `compile`; ไม่งั้น `assertion`
5. `git worktree remove --force` ใน `finally` เสมอ
6. เขียน `redgreen.json`: `{"ref":"<sha>","rows":[{"test":"tests/a.test.ts","kind":"assertion","evidence":"<last 5 lines>"}]}`

tester ห้ามแตะ worktree เอง และห้าม mutate production code เพื่อพิสูจน์ (ตัดข้อนี้จาก 0.16)

### 7.4 `hs gate conflict` (parallel เท่านั้น)

1. `changed = git diff --name-only base_ref -- . ':(exclude).happysquad' ':(exclude)knowledge'` ∪ `git ls-files --others --exclude-standard` (exclude เดียวกัน)
2. ทุกไฟล์ใน `changed` ต้อง map ไป `owned` ∪ `test_owned` ของ workstream เดียวพอดี
3. integration: รัน `config.build_cmd` + `config.test_cmd` ถ้าตั้งไว้ ไม่งั้น union ของ `build_cmds` + `test_cmds` ที่ทุก workstream บันทึก (dedupe)
4. `conflict.json`: `{"ok":bool,"violations":[{"file":"...","owners":[...],"reason":"unowned|multi-owner"}],"integration":{"exit":0}}` fail → ARCHITECT, `iteration += 1`

single/lite: ข้าม เขียน `{"ok":true,"skipped":"single"}`

### 7.5 `hs verify`

รันทุก `verify` ที่ไม่ใช่ `manual` ผ่าน `sh -c` timeout 300s `verify.json`: `{"R-1":"pass","R-2":"fail","R-3":"manual"}` `--dry` แค่ตรวจว่า string ไม่ว่าง ไม่ใช่ `manual` และ `sh -n` ผ่าน

### 7.6 `hs risk`

patterns จาก `references/risk-patterns.json` merge กับ `.happysquad/risk-patterns.json` (user เพิ่ม/ปิดได้) โครง:

```json
{"sec":{"paths":["(?i)auth","(?i)token","(?i)secret","(?i)payment",...],
        "diff":["(?i)cors","Content-Security-Policy",...],
        "manifest_deps":true},
 "perf":{"paths":["(?i)migration","(?i)queue","(?i)worker"],
         "diff":["\\bSELECT\\b","\\.findMany\\(","fetch\\(","(?i)cache",...]}}
```

ทำงานบน diff ที่ exclude `.happysquad` และ `knowledge` แล้ว ผล `risk.json`: `{"axes":["sec"],"matches":[{"file":"src/auth.ts","axis":"sec","pattern":"(?i)auth"}]}`

## 8. State machine

```
ARCHITECT ──▶ IMPLEMENT(waves) ──▶ TEST(waves) ──▶ CONFLICT ──▶ RISK ──▶ REVIEW ──┬─▶ COMPLETE
   ▲                                                                              │
   │◀────────────────── route=architecter / CONFLICT fail / ownership_gap ◀────────┤
   │                                                                              │
   │         ┌──── all blockers verifiable ────▶ INNER_FIX ──▶ verify ──▶ gates ──▶ REVIEW(delta)
   │         │
   └── FAIL ─┴──── any manual blocker ────────▶ IMPLEMENT/TEST (subset) ──▶ ... ──▶ REVIEW
```

### 8.1 กฎ transition

- `ARCHITECT` ok → `IMPLEMENT` wave 1 (`parallel=false` หรือ `--no-parallel` → workstream เดียว) ก่อน dispatch ครั้งแรกของทุก iteration ที่ไม่ใช่ 1: `iter_ref = hs snapshot`
- ทุก `IMPLEMENT` wave จบ → `gate build` ต่อ workstream → wave ถัดไป → เมื่อครบทุก wave → `TEST` wave 1 (DAG เดียวกัน)
- ทุก `TEST` wave จบ → `gate test` ต่อ workstream
- `CONFLICT` → `RISK` → `REVIEW`: dispatch chief + specialist ต่อ axis ใน `risk.json` พร้อมกัน (`dispatch_many`) chief รอ specialist ไม่ได้ → hs จึง dispatch specialist **ก่อน** รอครบ แล้ว dispatch chief พร้อม path ของ specialist reports (ยอมเสีย wall-clock เพื่อให้ chief เห็น specialist จริง; เดิมบอก "parallel" แต่ chief อ่านไฟล์ที่ยังไม่มี)
- `REVIEW` → hs คำนวณ verdict (§6.4) → `COMPLETE` หรือ routing (§8.2)
- `iteration` นับที่ทุก `REVIEW` ที่ไม่ใช่ delta ซ้ำใน inner loop; `iteration > cap` → BLOCKED

### 8.2 Routing เมื่อ FAIL

1. เขียน `feedback.md` (§9.3)
2. convergence (§8.3) อาจ override route
3. ถ้า route ∈ {implementer, tester} และทุก blocker มี `verify ≠ manual` และ `inner_pass < inner_cap` → `INNER_FIX`: dispatch fix agent (implementer ก่อน tester ถ้าทั้งคู่) ด้วย `prompts/fix.md` → `hs verify` → ทั้งหมด pass → `gate build` + `gate test` เต็ม → `CONFLICT` (parallel) → `REVIEW` mode `delta` (chief เท่านั้น ยกเว้น `hs risk` บนไฟล์ที่ fix แตะเจอ axis ใหม่) → verify fail → `inner_pass += 1` วนใหม่ → เกิน `inner_cap` → full round
4. ไม่งั้น full round: `IMPLEMENT`/`TEST` subset workstreams ที่ blockers ระบุ หรือ `ARCHITECT`

### 8.3 Convergence (fingerprint)

`fp = sha1(tag + "|" + file + "|" + normalize(desc))` โดย `normalize` = lowercase, ตัด digits/quotes/whitespace, ตัด token ที่ยาวกว่า 40 ตัว hs เก็บ `fingerprints[fp].seen = [iterations]`

- seen ครั้งที่ 2 (repeat แรก) → route ปกติ
- seen ครั้งที่ 3 → บังคับ `architecter` (ถ้ายังไม่ escalate ดู §8.6)
- seen หลัง iteration ที่ route=architecter → BLOCKED
- round ที่ `resolved = 0` (ไม่มี blocker เก่าหายไปเลย) → บังคับ `architecter`; สองรอบติด → BLOCKED

reviewer ไม่ต้องกรอก Recurrence อีก hs ใส่ `## Prior findings` ใน review prompt ให้ chief เห็นเพื่อให้คง id/desc ใกล้เดิม

### 8.4 Gate retry

validation fail หรือ gate build/test fail → re-dispatch phase เดิมพร้อม feedback, `gate_retry += 1`, phase dir suffix `-r<n>` เกิน `gate_retries` (default 1) → BLOCKED พร้อมเหตุผล "evidence gate failed N times" reset `gate_retry` เมื่อ phase ผ่าน

### 8.5 Lite path

เข้าเมื่อ `--lite` หรือ (`size=S` ∧ `lite.auto`) ∧ ไม่ `--full`:
- design ใช้ `design-template-lite.md` (task, AC, owned files, notes) architecter ส่ง workstream เดียว
- ข้าม `CONFLICT`, `RISK`; `review_mode=single`; cap = `lite.cap` (default 3)
- red→green, gate build/test, inner fix loop, convergence ยังทำครบ (ถูกเพราะเป็น script)

### 8.6 Escalation

`config.escalation.model` (default null = ปิด) เมื่อ fingerprint ใด seen ครั้งที่ 3 และ `escalated=false`: dispatch fix round นั้นด้วย `escalation.model` แทน model ปกติของ agent ที่ route ไป, set `escalated=true`, event `escalate` หลังจากนั้น convergence ปกติ (repeat อีก → architecter → BLOCKED) ใช้ได้กับ model ใดก็ได้ที่ Agent tool รับ

### 8.7 BLOCKED

`BLOCKED.md`: task, ตาราง iteration/verdict/route จาก events, blockers ปัจจุบัน, convergence (fingerprint, seen, routes, ลองอะไรไปแล้วจาก feedback ทุกรอบ), gate failures, escalation ที่ทำไป, recommended action hs เขียนทั้งหมดจาก events + out.json ไม่มี LLM

### 8.8 Resume และ recovery

`hs resume`:
1. อ่าน `pending` ทุกรายการที่ `out_file` มีอยู่ → consume ตามปกติ (event `recover`)
2. รายการที่ไม่มี out.json แต่ phase dir ถูกแตะใน 10 นาที → `wait`
3. ที่เหลือ → re-dispatch (prompt เดิม)
4. ไม่มี pending → `next`
BLOCKED/COMPLETE ไม่ resume `--run <id>` เลือก run อื่นได้

### 8.9 Context checkpoint

hs นับ iteration และจำนวน dispatch; เมื่อ iteration ≥ 3 หรือ dispatch ≥ 12 ใน session เดียว (hs รู้ session จาก `.happysquad/.session` ที่ hook เขียน) `next` คืน `{"action":"checkpoint","handoff":"HANDOFF.md"}` หนึ่งครั้ง orchestrator พิมพ์ข้อความให้ user เปิด session ใหม่แล้ว `/squad-resume` ถ้า `interactive=false` หรือ driver=headless → ข้าม

## 9. Prompts

### 9.1 Template rendering

`prompts/<phase>.md` ใช้ `{{var}}` แทนที่ด้วย `str.replace` ไม่มี logic ตัวแปร: `run_id, iteration, task, task_file, design_path, feedback_path, implementation_path, test_report_path, owned_files (bullet list), test_owned_files, workstream, ac_list, base_ref, iter_ref, proof_ref, skills (bullet), out_file, phase_dir, verified_coverage, threshold, risk_axes, specialist_reports (bullet), prior_findings (table), mode, model, build_cmd, test_cmd` ตัวแปรที่ไม่มีค่า render เป็น `(none)`

dispatch prompt ≤ 200 คำ บอกแค่: บทบาท (ซ้ำสั้น ๆ), input paths, output ที่ต้องเขียน (artifact + out.json), ข้อห้าม 2–3 ข้อ ความรู้เรื่องวิธีทำงานอยู่ใน agent .md (system prompt)

### 9.2 Agent files

| agent | model | tools | ขอบเขต |
|---|---|---|---|
| architecter | opus | Read, Grep, Glob, Write | เขียนเฉพาะใน phase dir; design.md ตาม template; out.json §6.1; อ่าน wiki subsystems/patterns/decisions ก่อน |
| implementer | sonnet | Read, Write, Edit, Grep, Glob, Bash | แก้เฉพาะ owned; รัน build เอง; ไม่เขียนเทสใหม่; out.json §6.2 |
| tester | sonnet | Read, Write, Edit, Grep, Glob, Bash | แก้เฉพาะ test_owned; เรียก `hs redgreen`; ไม่แตะ production; out.json §6.3 |
| reviewer | opus | Read, Grep, Glob, Bash, Write | อ่าน diff เอง เสมอ; เขียนเฉพาะ phase dir; verify command ต่อ finding; `hs verify --dry`; delta mode; out.json §6.4 |
| specialist | opus | Read, Grep, Glob, Bash, Write | axis เดียวตาม `references/axis-<axis>.md`; out.json |
| product | opus | Read, Grep, Glob, Write | brainstorm เท่านั้น |

ทุก agent ตัด: brainstorm mode, token discipline, marker format, คำอธิบายเหตุผลยาว, ตาราง markdown ที่ hs parse แทนแล้ว คงไว้: กฎคุณภาพที่เป็นวิจารณญาณ (round-trip over hardcoded, chief reads the diff, mocked DB ไม่นับ coverage, scale assumptions จาก design, wiki lessons = blocker)

### 9.3 `feedback.md` (hs เขียน)

```
# Feedback for iteration <N+1>  (target: implementer | workstream: backend)
## Blockers
| id | tag | file:line | desc | verify |
## Majors (fix if cheap)
## Failing verify (inner pass ≥ 2)
## Gate failure (ถ้ามี)
## Reviewer summary
<บรรทัดแรกของ review.md ส่วน Summary>
```

## 10. Orchestrator skill (`skills/squad-loop/SKILL.md`)

เนื้อหาทั้งหมด ≤ 400 คำ:

1. `hs run start "<task>" <flags>` (หรือ `hs resume`) อ่าน action
2. ทำตาม action:
   - `dispatch` / `dispatch_many`: เรียก Agent tool (`subagent_type: happysquad:<agent>`, `model`, prompt = เนื้อหา `prompt_file`, cwd ถ้ามี) ทั้ง wave ในข้อความเดียว
   - `wait`: Bash `run_in_background`: `until all -s out_files; do sleep 5; done` (timeout 5400000) รอ notification; ถ้า Agent tool คืนผลก่อน ไม่ต้องรอ
   - `ask`: AskUserQuestion → `hs answer <key> <value>`
   - `checkpoint`: บอก user แล้วหยุด
   - `done`: รายงาน ≤ 150 คำจาก field ของ action; ถ้า `wiki_offer` ถาม 1 ครั้ง
3. หลัง agent กลับ (หรือ wait จบ): `hs advance` → กลับข้อ 2

กฎ: ไม่อ่าน design/review/evidence เอง; ไม่แก้ state; agent error → retry 1 ครั้ง, ครั้งที่ 2 `hs block "agent error: ..."`; ไม่จบ turn ขณะมี dispatch ค้าง

## 11. Drivers

`config.driver` หรือ `--driver`:

- **`agent-tool`** (default): orchestrator LLM ตาม §10
- **`headless`**: `hs run start --driver headless` วน loop ภายใน hs เอง: ทุก dispatch = `subprocess` `claude -p "$(cat prompt)" --model <m> --permission-mode acceptEdits --allowedTools "Read,Write,Edit,Grep,Glob,Bash" --max-budget-usd <config.headless.budget_per_phase> --append-system-prompt-file agents/<agent>.md` wave = concurrent subprocesses (≤ `max_parallel`) ไม่มี session เปิด; ใช้สำหรับ overnight, CI, fleet children
- **`fake`**: dispatch = `python3 evals/fake_agent.py <prompt_file> <out_file> --scenario <name>` เขียน out.json + artifacts ตาม scenario ใช้ใน `test_hs.py` e2e ฟรี

fleet children ใช้ `headless` เสมอ (ไม่ nest Agent tool 2 ชั้น)

## 12. Fleet

- `hs fleet start`: task จากไฟล์ หรือ `--frontier` (`hs frontier`) สร้าง worktree `fleet/<fleet-id>/<slug>` จาก base branch; `--drain` = frontier only, max 1, pump on, ไม่มี prompt, frontier ว่าง → exit 0 เงียบ
- children รัน `hs run start --driver headless` ใน worktree (`parent_fleet_id` set) parent poll `<wt>/.happysquad/state.json`
- `hs fleet advance`: reconcile (COMPLETE/BLOCKED/quiet 30 นาที → `stalled`), dispatch pending จนครบ `max_parallel`
- `aggregate-report.md` + merge commands เหมือนเดิม ไม่ auto-merge ไม่ลบ worktree เว้นแต่ `--cleanup`
- `squad:passed` label/marker บน ticket เมื่อ child COMPLETE (ถ้า tracker รองรับ)

`skills/fleet/SKILL.md` ≤ 300 คำ: เรียก `hs fleet start` → loop `hs fleet advance` + wait

## 13. Brainstorm, stack-detector, dev-wiki

- **brainstorm**: โครง 3 รอบเดิม round instructions ย้ายไป `prompts/brainstorm/*.md` session state เป็น `session.json` ที่ hs เขียน (`hs brainstorm start|advance`) agents เขียน `out.json` `{"round":1,"agent":"product","file":"round1-product.md"}` และ signoff `{"verdict":"APPROVE|DISSENT","smallest_change":"..."}` convergence คำนวณโดย hs
- **stack-detector**: เหมือนเดิม แต่ mapping อ่านจาก `references/skill-map.json` merge กับ `.happysquad/skill-map.json` ตรวจกับ `<available_skills>` ตอน run; ไม่มีชื่อ plugin ส่วนตัวใน core
- **dev-wiki**: เหมือนเดิม ส่วน deterministic ของ lint เป็น `hs wiki lint` (index consistency, broken links, raw refs, see-also prune) heuristic ยังเป็น LLM

## 14. Commands (11)

| command | ทำอะไร |
|---|---|
| `/happysquad-loop <task> [--lite\|--full] [--no-parallel] [--driver X]` | §10 |
| `/squad-architect <task>` | `hs run start` + ARCHITECT เท่านั้น แล้วหยุด (run ค้างไว้ resume ต่อได้) |
| `/squad-review [--base <ref>]` | `hs run review-only`: base_ref = merge-base, สร้าง run ที่ข้ามไป gate test (ถ้ามี test_cmd) → RISK → REVIEW รายงานแล้วหยุด |
| `/squad-status` | `hs status` |
| `/squad-resume` | `hs resume` + §10 |
| `/squad-fleet [<file>] [--frontier] [--max N] [--drain]` | §12 |
| `/squad-detect` | stack-detector |
| `/brainstorm <topic> [--rounds=2] [--quick]` | §13 |
| `/wiki-ingest`, `/wiki-ask`, `/wiki-lint` | เดิม |

ตัด: `/squad-implement`, `/squad-test`, `/squad-assemble`, `/ask-kilo`, `/squad-drain`

## 15. Hooks

```json
{"hooks":{
  "SessionStart":[{"hooks":[{"type":"command","command":"python3 \"${CLAUDE_PLUGIN_ROOT}/bin/hs\" hook session-start"}]}],
  "Stop":[{"hooks":[{"type":"command","command":"python3 \"${CLAUDE_PLUGIN_ROOT}/bin/hs\" hook stop"}]}]}}
```

- `session-start`: ไม่มี `.happysquad/` → เงียบ; มี → เขียน `.happysquad/.session` (id + ts), พิมพ์ resume nudge ≤ 5 บรรทัดเฉพาะเมื่อมี run/fleet/brainstorm ค้าง; DRIFT warning คงไว้ (commit หลัง `updated_at`); ไม่พิมพ์ git log
- `stop`: ทำงานเฉพาะ `config.hooks.stop_progress_nudge=true` logic เดิม (one-shot) exit 2
- hooks ห้าม fail session (exit 0 เสมอ ยกเว้น nudge exit 2) ห้ามใช้ `rtk`

## 16. Config

### 16.1 Schema + defaults (ฝังใน hs; `hs config` พิมพ์ effective)

```json
{"driver":"agent-tool","interactive":true,
 "cap":5,"inner_cap":2,"gate_retries":1,"gate_timeout":600,
 "coverage_threshold":80,"review_mode":"split-on-risk",
 "max_parallel":4,
 "models":{"architecter":"opus","implementer":"sonnet","tester":"sonnet","reviewer":"opus","specialist":"opus","product":"opus"},
 "escalation":{"model":null},
 "lite":{"auto":true,"cap":3},
 "build_cmd":null,"test_cmd":null,"coverage_report":null,
 "headless":{"budget_per_phase":2.0,"allowed_tools":"Read,Write,Edit,Grep,Glob,Bash"},
 "hooks":{"stop_progress_nudge":false},
 "wiki":{"offer":true},
 "fleet":{"base_branch":null}}
```

key ที่ไม่รู้จัก → warning ครั้งเดียว ไม่ fail

### 16.2 Non-interactive defaults (`interactive=false`)

| key | default |
|---|---|
| `resume_existing` | resume |
| `stack_profile_stale` | refresh |
| `claude_md_missing` | skip |
| `dirty_tree` | proceed (snapshot เป็น base_ref) |
| `team_plan_mismatch` | (ตัดแล้ว) |
| `wiki_offer` | no |
| `brainstorm_proceed` | stop (ไม่ auto-pipe) |
| `fleet_cleanup` | keep |
| `fleet_wiki_ingest` | no |
| `checkpoint` | skip |

## 17. Git hygiene

- `hs init` เขียน `.happysquad/.gitignore`: `*`, `!.gitignore`, `!config.json`, `!stack-profile.md`, `!stack-profile.json`, `!risk-patterns.json`, `!skill-map.json` ไม่แตะ root `.gitignore`
- ทุก diff ใน hs: `-- . ':(exclude).happysquad' ':(exclude)knowledge'` + untracked ผ่าน `git ls-files --others --exclude-standard`
- `base_ref` และ `iter_ref` เป็น dangling commit จาก `hs snapshot` เสมอ (temp index, `git add -A`, `write-tree`, `commit-tree -p HEAD`) ทำให้ "สภาพ tree ตอนเริ่ม" นิยามเดียวไม่ว่าจะ dirty หรือไม่; repo ไม่มี commit → `base_ref=null`, redgreen = not-runnable
- hs ไม่ commit/branch/push ยกเว้น fleet worktree branches `done` action มี `suggested_commit` ให้ user

## 18. Evals

### 18.1 `evals/test_hs.py` (unittest, stdlib, ไม่เรียก model, < 30 วินาที)

- schema validation ทุก phase (missing key, wrong type, owned overlap, non-DAG, AC ไม่ครอบ)
- coverage parsers 4 format จาก fixtures + per-file
- redgreen classification (green/compile/assertion/not-runnable) บน toy repo
- verdict/route derivation ทุกกรณี (CONFLICT, architecter, mixed, SIMPL cap)
- convergence: repeat 3 → architecter, repeat after architecter → BLOCKED, zero-progress ×2 → BLOCKED
- inner loop: eligible/ineligible, inner_cap, fallback
- gate retry → BLOCKED
- lite path transitions
- risk matching + exclude paths
- conflict gate: unowned, multi-owner, untracked
- resume/recover: out.json on disk, quiet, re-dispatch
- fake-driver e2e scenarios: `pass-first`, `fail-inner-fix`, `fail-full-round`, `repeat-escalate`, `blocked-convergence`, `parallel-2ws`, `ownership-gap`, `gate-build-fail`, `lite`
- fleet: 2 children fake, one BLOCKED, aggregate

### 18.2 `evals/smoke.sh`

toy repo + `claude -p` headless driver 1 loop, `--max-budget-usd 3`, sonnet ทุก agent, assert `COMPLETE` + coverage ≥ 80 รันก่อน tag ทุกครั้ง

### 18.3 CI

`python3 -m unittest discover -s evals` บน push; smoke manual

## 19. แผนงานและ acceptance criteria

| phase | งาน | AC |
|---|---|---|
| **P1 hs core** (ครึ่งหนึ่งของทั้งหมด) | `bin/hs`: config, init, snapshot, state/events, schemas, gates build/test/conflict, redgreen, verify, risk, transitions, convergence, feedback, BLOCKED, resume, status, prompt render; `test_hs.py` ยกเว้น e2e; fixtures | `test_hs.py` ผ่าน; `hs gate test` parse 4 format; `hs redgreen` บน toy repo ให้ assertion/compile ถูก; skill 0.16 ยังใช้ได้ (ไม่แตะ) |
| **P2 driver + agents** | squad-loop SKILL.md ใหม่; 6 agent files; prompts/; out.json; fake driver + 9 scenarios; smoke | fake e2e ผ่านทุก scenario; smoke COMPLETE; word budgets ตาม §9.2 |
| **P3 cuts + ops** | ย้าย §2 ไป repo `happysquad-ext` แล้วลบจาก core; hooks ใหม่; non-interactive; lite; `.gitignore`; config schema; README/CHANGELOG; tag v1.0.0-rc1 | ไม่มี AskUserQuestion เมื่อ `interactive=false` (ตรวจด้วย fake + headless); `/happysquad-loop --lite` บน bug 1 ไฟล์ ≤ 4 dispatch |
| **P4 fleet/brainstorm/wiki** | `hs fleet`, `hs frontier`, headless children, `--drain`; `hs brainstorm`; `hs wiki lint`; skill-map.json; tag v1.0.0 | fleet fake e2e ผ่าน; `/squad-fleet --drain` บน frontier ว่าง exit เงียบ; `hs wiki lint` ตรงกับผล lint เดิมบน fixture wiki |

## 20. ข้อแลกเปลี่ยนและการตัดสินใจ

ตัดสินใจแล้ว (พี่จี, 2026-10-02):

- **specialist dispatch ก่อน chief (ไม่ parallel)** — ยืนยัน เสีย wall-clock หนึ่ง specialist round เฉพาะเมื่อ risk match แลกกับ chief เห็น report จริง
- **reviewer ไม่ส่ง verdict, hs คำนวณ** — ยืนยัน blocker ใด ๆ = FAIL เสมอ ตัด inconsistency แบบ PASS ทั้งที่มี blocker
- **ownership overlap ไม่มี worktree fallback** — ยืนยัน overlap = design ผิด re-dispatch architecter พร้อมเหตุผล
- **team-assembly / external executors / ask-kilo / fable escalation** — ย้ายไป plugin `happysquad-ext` ก่อนลบจาก core (P3) ไม่ต้องใช้ได้ใน v1.0

ยอมรับแล้ว:

- **python3 เป็น hard dependency** macOS/Linux มี default; Windows ต้องติดตั้ง
- **run เก่าจาก 0.16 ใช้กับ v1.0 ไม่ได้** run เป็นของชั่วคราว; `hs status` บอกให้ลบหรือ archive

ยังเปิด:

- **headless budget** `budget_per_phase` 2.0 USD เพียงพอไหมสำหรับ opus review บน diff ใหญ่ → วัดจาก smoke ใน P2
