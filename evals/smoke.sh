#!/usr/bin/env bash
# P0 spike / release smoke: a real `claude -p` orchestrator drives /hs-loop on a throwaway toy repo.
#
#   evals/smoke.sh [--tasks N] [--budget USD] [--model sonnet|opus] [--keep]
#
# Asserts: every run reaches COMPLETE, no `ask` actions, and prints dispatch count + cost.
# The toy's first test gate sleeps ~150s (HS_GATE=1) so a wait > 120s is exercised.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGIN="$(cd "$HERE/.." && pwd)"
TASKS=1; BUDGET=6; MODEL=sonnet; KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --tasks) TASKS="$2"; shift 2;;
    --budget) BUDGET="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --keep) KEEP=1; shift;;
    *) echo "unknown arg $1"; exit 2;;
  esac
done

WORK="$(mktemp -d /tmp/hs-smoke-XXXXXX)"
cp -R "$HERE/fixtures/toy-repo/." "$WORK/"
cd "$WORK"
git init -q && git add -A && git -c user.email=t@t -c user.name=t commit -qm init
"$PLUGIN/bin/hs" init >/dev/null
cat > .happysquad/config.json <<EOF
{"build_cmd":"npm run build","test_cmd":"npm test","coverage_report":"coverage/lcov.info",
 "redgreen_cmd":"npm test -- {file}","interactive":false,"cap":3,
 "models":{"architecter":"$MODEL","implementer":"$MODEL","tester":"$MODEL","reviewer":"$MODEL"}}
EOF

T1="add mul(a, b) to src/calc.js returning a*b, with a test in test/mul.test.js"
T2="add div(a, b) to src/calc.js that throws RangeError on b === 0, with tests in test/div.test.js"
T3="add clamp(x, lo, hi) to src/calc.js, with tests in test/clamp.test.js covering both bounds"
case "$TASKS" in
  1) PROMPT="/happysquad:hs-loop $T1";;
  2) PROMPT="Run /happysquad:hs-loop for each task below, finishing one completely (until its done action) before starting the next. Task 1: $T1 Task 2: $T2";;
  *) PROMPT="Run /happysquad:hs-loop for each task below, finishing one completely (until its done action) before starting the next. Task 1: $T1 Task 2: $T2 Task 3: $T3";;
esac

LOG="$WORK/claude.stream.jsonl"
echo "work: $WORK"
echo "prompt: $PROMPT"
set +e
claude -p "$PROMPT" \
  --plugin-dir "$PLUGIN" \
  --settings '{"enabledPlugins":{"happysquad@happytech.dev":false}}' \
  --permission-mode acceptEdits \
  --allowedTools "Bash Read Write Edit Glob Grep Agent Skill" \
  --max-budget-usd "$BUDGET" \
  --output-format stream-json --verbose \
  > "$LOG" 2> "$WORK/claude.stderr"
RC=$?
set -e

python3 - "$WORK" "$LOG" "$RC" <<'PY'
import glob, json, os, sys
work, log, rc = sys.argv[1], sys.argv[2], int(sys.argv[3])
runs = sorted(glob.glob(os.path.join(work, ".happysquad", "runs", "*")))
total_dispatch = 0; ok = True; asks = 0
for r in runs:
    st = json.load(open(os.path.join(r, "state.json")))
    evs = [json.loads(l) for l in open(os.path.join(r, "events.jsonl")) if l.strip()]
    d = sum(1 for e in evs if e["event"] == "dispatch")
    a = sum(1 for e in evs if e["event"] == "ask")
    total_dispatch += d; asks += a
    print("run %s: state=%s iter=%s dispatches=%d asks=%d cause=%s" % (os.path.basename(r), st["state"], st["iteration"], d, a, st.get("block_cause")))
    ok = ok and st["state"] == "COMPLETE"
cost = None; turns = None
try:
    for l in open(log):
        try:
            m = json.loads(l)
        except ValueError:
            continue
        if m.get("type") == "result":
            cost = m.get("total_cost_usd"); turns = m.get("num_turns")
except FileNotFoundError:
    pass
print("claude rc=%s turns=%s cost_usd=%s" % (rc, turns, cost))
print("TOTAL dispatches=%d asks=%d runs=%d" % (total_dispatch, asks, len(runs)))
print("SMOKE", "PASS" if (ok and runs and asks == 0) else "FAIL")
sys.exit(0 if (ok and runs and asks == 0) else 1)
PY
RES=$?
[ "$KEEP" = 1 ] && echo "kept: $WORK" || true
exit $RES
