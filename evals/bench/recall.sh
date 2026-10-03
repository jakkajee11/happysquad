#!/usr/bin/env bash
# Seeded-bug recall (spec §18.2): hand a reviewer the seeded-bugs diff and score its findings.
#
#   evals/bench/recall.sh 0.16|hs [--model sonnet|opus] [--budget USD]
#
# Both engines review the same artefact: evals/fixtures/seeded-bugs/diff.patch applied to a
# throwaway copy of the repo at HEAD, so `git diff` shows exactly the three planted edits.
# 0.16: dispatch agents/reviewer.md's prompt as a single `claude -p --agent reviewer` with a
#       review instruction that mirrors a squad review (design = "no behaviour change; refactor").
# hs:   render prompts/review.md through the engine (REVIEW phase of a synthetic run) and run it
#       with the hs reviewer system prompt via the headless argv builder.
# Score: evals/fixtures/seeded-bugs/score.py on the resulting findings.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGIN="$(cd "$HERE/../.." && pwd)"
ENGINE="${1:?0.16|hs}"; shift
MODEL=sonnet; BUDGET=3
while [ $# -gt 0 ]; do
  case "$1" in
    --model) MODEL="$2"; shift 2;;
    --budget) BUDGET="$2"; shift 2;;
    *) echo "unknown arg $1"; exit 2;;
  esac
done
TS="$(date -u +%Y%m%d-%H%M%S)"
OUT="$HERE/results/recall-$ENGINE-$TS"; mkdir -p "$OUT"
W="$(mktemp -d /tmp/hs-recall-XXXXXX)"
git -C "$PLUGIN" worktree add -q --detach "$W" HEAD
# apply the planted defects onto hs/ so `git diff` is exactly the three bugs
( cd "$W" && for f in machine.py gates.py gitutil.py; do cp "evals/fixtures/seeded-bugs/hs/$f" "hs/$f"; done )
BASE="$(git -C "$W" rev-parse HEAD)"
git -C "$W" diff --stat > "$OUT/diff.stat"

DESIGN='# Design (recall fixture)

Task summary: internal cleanup of the hs engine — simplify ref comparison, test-gate aggregation and the snapshot helper. No behaviour change intended.

Acceptance criteria:
- AC-1: red→green ref checks still reject a mismatched ref.
- AC-2: the test gate still fails when any test command exits non-zero.
- AC-3: snapshot never modifies the user'"'"'s real git index.'

mkdir -p "$W/.happysquad/runs/recall/REVIEW-i1"
printf '%s\n' "$DESIGN" > "$W/.happysquad/runs/recall/design.md"

case "$ENGINE" in
  0.16)
    PROMPT="You are the chief reviewer. Review the uncommitted diff in this repo (git diff HEAD) against the design at .happysquad/runs/recall/design.md. Read every changed file first-hand. Write .happysquad/runs/recall/review.md in the squad review format (per-axis verdicts and an Issues table with columns | ID | Severity | Tag | File:Line | Description | Source | Route to | Workstream | Verify | Recurrence |). Severity blocker for any real defect. Then end with the REVIEW_READY marker line."
    ARGS=(--agents "$(python3 - <<'PY'
import json, re, sys, os
p = os.path.join(sys.argv[0] if False else ".", "agents", "reviewer.md")
PY
)")
    # build --agents from the 0.16 reviewer file (frontmatter tools + body as prompt)
    AGENTS="$(python3 - "$PLUGIN/agents/reviewer.md" <<'PY'
import json, sys
text = open(sys.argv[1]).read()
head, _, body = text[3:].partition("\n---")
tools = []
for line in head.splitlines():
    if line.startswith("tools:"):
        tools = [t.strip() for t in line.split(":", 1)[1].split(",") if t.strip()]
if "Write" not in tools: tools.append("Write")
print(json.dumps({"reviewer": {"description": "0.16 chief reviewer", "prompt": body.strip(), "tools": tools}}))
PY
)"
    ( cd "$W" && claude -p "$PROMPT" --agents "$AGENTS" --agent reviewer --model "$MODEL" \
        --permission-mode acceptEdits --allowedTools "Read,Grep,Glob,Bash,Write" \
        --max-budget-usd "$BUDGET" --output-format json < /dev/null > "$OUT/claude.json" 2> "$OUT/claude.stderr" ) || true
    cp "$W/.happysquad/runs/recall/review.md" "$OUT/review.md" 2>/dev/null || echo "(no review.md)" > "$OUT/review.md"
    python3 "$PLUGIN/evals/fixtures/seeded-bugs/score.py" --md "$OUT/review.md" | tee "$OUT/score.txt"
    ;;
  hs)
    # render the real REVIEW prompt through hs: a synthetic single-ws run whose state says REVIEW
    python3 - "$W" "$BASE" "$PLUGIN" <<'PY'
import json, os, sys
w, base, plugin = sys.argv[1:4]
sys.path.insert(0, plugin)
from hs import machine, state as S, config as C
rid = "recall"
rd = S.run_dir(w, rid); os.makedirs(os.path.join(rd, "prompts"), exist_ok=True)
st = {"run_id": rid, "task": "internal cleanup of the hs engine (recall fixture)", "driver": "headless", "mode": "single", "lite": False,
      "review_mode": "single", "base_ref": base, "iter_ref": None, "proof_ref": base, "proven": [],
      "state": "REVIEW", "iteration": 1, "inner_pass": 0, "gate_retry": 0, "validation_retry": 0, "retry": 0,
      "cap": 3, "inner_cap": 2, "coverage_threshold": None,
      "cmds": {"build": "python3 -m py_compile hs/machine.py hs/gates.py hs/gitutil.py", "test": "python3 -m unittest discover -s evals -p test_hs.py", "coverage_report": None},
      "workstreams": [{"name": "hs", "owned": ["hs/*.py"], "depends_on": [], "ac": ["AC-1", "AC-2", "AC-3"], "impl": "done", "test": "done"}],
      "untestable": [], "test_owned": {"hs": ["evals/test_*.py"]}, "ws_impl_files": {"hs": ["hs/machine.py", "hs/gates.py", "hs/gitutil.py"]},
      "impl_phase_dirs": [], "test_phase_dirs": [], "review_phase_dirs": [], "pending": [], "gates": {}, "findings": {},
      "arch_iterations": [], "zero_progress": 0, "risk": None, "specialists": {}, "specialist_reports": [], "inner_verify": {}, "delta": False,
      "last_test_gate": {"tests": "pass", "coverage": {"status": "unsupported", "rule": "delta", "per_file": {}, "unverified": []}, "redgreen": {"ref": base, "rows": []}},
      "started_at": S.now()}
S.save_state(rd, st); S.set_current(w, rid)
cfg = C.load(w)
act = machine.dispatch(w, rid, cfg)
print(json.dumps({k: act.get(k) for k in ("action", "prompt_file", "out_file")}))
PY
    PF="$(python3 -c "import json,glob;print(glob.glob('$W/.happysquad/runs/recall/prompts/REVIEW-i1*.md')[0])")"
    AGENTS="$(python3 - "$PLUGIN" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[1])
from hs import drivers
print(json.dumps(drivers.agents_json("reviewer")))
PY
)"
    ( cd "$W" && HS_CHILD=1 claude -p "$(cat "$PF")" --agents "$AGENTS" --agent reviewer --model "$MODEL" \
        --permission-mode acceptEdits --allowedTools "Read,Grep,Glob,Bash,Write" \
        --max-budget-usd "$BUDGET" --output-format json < /dev/null > "$OUT/claude.json" 2> "$OUT/claude.stderr" ) || true
    cp "$W/.happysquad/runs/recall/REVIEW-i1/out.json" "$OUT/out.json" 2>/dev/null || echo '{"phase":"REVIEW","mode":"single","report":"review.md","findings":[]}' > "$OUT/out.json"
    cp "$W/.happysquad/runs/recall/REVIEW-i1/review.md" "$OUT/review.md" 2>/dev/null || true
    python3 "$PLUGIN/evals/fixtures/seeded-bugs/score.py" "$OUT/out.json" | tee "$OUT/score.txt"
    ;;
  *) echo "engine must be 0.16 or hs"; exit 2;;
esac
python3 - "$OUT/claude.json" <<'PY'
import json, sys
try:
    m = json.load(open(sys.argv[1])); print("claude: subtype=%s turns=%s cost=%s" % (m.get("subtype"), m.get("num_turns"), m.get("total_cost_usd")))
except Exception as e:
    print("claude: (no json result: %s)" % e)
PY
git -C "$PLUGIN" worktree remove --force "$W" >/dev/null 2>&1 || rm -rf "$W"
echo "results: $OUT"
