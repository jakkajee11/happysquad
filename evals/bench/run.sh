#!/usr/bin/env bash
# Bench runner (spec §18.2). One task, one engine, one throwaway worktree, one headless claude -p.
#
#   evals/bench/run.sh <B1..B5> <0.16|hs> [--budget USD] [--model sonnet|opus] [--keep]
#
# Writes evals/bench/results/<task>-<engine>-<ts>/{summary.json,claude.stream.jsonl,claude.stderr}
# and prints the summary line. Oracle: `python3 evals/cov.py -p test_hs.py` exits 0 in the worktree
# after the run reports completion.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGIN="$(cd "$HERE/../.." && pwd)"
TASK="${1:?task id B1..B5}"; ENGINE="${2:?engine 0.16|hs}"; shift 2
BUDGET=8; MODEL=sonnet; KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --budget) BUDGET="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --keep) KEEP=1; shift;;
    *) echo "unknown arg $1"; exit 2;;
  esac
done

# task text = the row's second column in tasks.md (helper script: no backticks allowed in this file)
TEXT="$(python3 "$HERE/task_text.py" "$TASK")" || { echo "task $TASK not found in tasks.md"; exit 2; }

TS="$(date -u +%Y%m%d-%H%M%S)"
OUT="$HERE/results/$TASK-$ENGINE-$TS"; mkdir -p "$OUT"
WT="$(mktemp -d /tmp/hs-bench-XXXXXX)"
BASE="$(git -C "$PLUGIN" rev-parse HEAD)"
git -C "$PLUGIN" worktree add -q --detach "$WT" "$BASE"
# local, gitignored config travels with the worktree
mkdir -p "$WT/.happysquad"
cp "$PLUGIN/.happysquad/config.json" "$WT/.happysquad/config.json"
cp "$PLUGIN/.happysquad/stack-profile.md" "$PLUGIN/.happysquad/stack-profile.json" "$WT/.happysquad/" 2>/dev/null || true
# 0.16 reads models from config.json; hs reads them too. Force the bench model on both.
python3 - "$WT/.happysquad/config.json" "$MODEL" <<'PY'
import json, sys
p, m = sys.argv[1], sys.argv[2]
c = json.load(open(p))
c["models"] = {"architecter": m, "implementer": m, "tester": m, "reviewer": m, "specialist": m, "product": m}
c.setdefault("cap", 3); c["interactive"] = False
json.dump(c, open(p, "w"), indent=2)
PY

case "$ENGINE" in
  0.16)
    PROMPT="/happysquad:happysquad-loop $TEXT"
    SYS="You are running unattended. Wherever a skill tells you to ask the user (AskUserQuestion, yes/no offers, resume/restart prompts, wiki ingest offers, CLAUDE.md nudges, stack-profile refresh), do NOT ask: pick the recommended or default option and continue. Never end your turn while an agent you dispatched is still running."
    ;;
  hs)
    PROMPT="/happysquad:hs-loop $TEXT"
    SYS="You are running unattended. Never ask the user anything; follow the skill exactly."
    ;;
  *) echo "engine must be 0.16 or hs"; exit 2;;
esac

echo "task=$TASK engine=$ENGINE model=$MODEL budget=$BUDGET worktree=$WT"
cd "$WT"
START=$(date +%s)
set +e
claude -p "$PROMPT" \
  --plugin-dir "$PLUGIN" \
  --settings '{"enabledPlugins":{"happysquad@happytech.dev":false}}' \
  --append-system-prompt "$SYS" \
  --permission-mode acceptEdits \
  --allowedTools "Bash Read Write Edit Glob Grep Agent Skill" \
  --max-budget-usd "$BUDGET" \
  --output-format stream-json --verbose \
  > "$OUT/claude.stream.jsonl" 2> "$OUT/claude.stderr"
RC=$?
set -e
SECS=$(( $(date +%s) - START ))

# oracle: full unit suite + coverage in the worktree, independent of what the squad claimed
set +e
python3 evals/cov.py -p test_hs.py > "$OUT/oracle.log" 2>&1; ORACLE=$?
set -e

python3 - "$WT" "$OUT" "$TASK" "$ENGINE" "$MODEL" "$RC" "$SECS" "$ORACLE" "$BASE" <<'PY'
import glob, json, os, subprocess, sys
wt, out, task, engine, model, rc, secs, oracle, base = sys.argv[1:10]
rc, secs, oracle = int(rc), int(secs), int(oracle)
s = {"task": task, "engine": engine, "model": model, "claude_rc": rc, "secs": secs,
     "oracle_exit": oracle, "oracle": "pass" if oracle == 0 else "fail", "base": base}
# cost / turns from the stream
for l in open(os.path.join(out, "claude.stream.jsonl")):
    try: m = json.loads(l)
    except ValueError: continue
    if m.get("type") == "result":
        s["cost_usd"] = m.get("total_cost_usd"); s["turns"] = m.get("num_turns"); s["subtype"] = m.get("subtype")
# asks: any AskUserQuestion tool_use in the stream
asks = 0
for l in open(os.path.join(out, "claude.stream.jsonl")):
    try: m = json.loads(l)
    except ValueError: continue
    if m.get("type") == "assistant":
        for c in m.get("message", {}).get("content", []):
            if c.get("type") == "tool_use" and c.get("name") == "AskUserQuestion": asks += 1
s["asks"] = asks
# destructive actions: git push/reset/clean/checkout or rm -rf outside tmp in any Bash tool_use
bad = []
for l in open(os.path.join(out, "claude.stream.jsonl")):
    try: m = json.loads(l)
    except ValueError: continue
    if m.get("type") == "assistant":
        for c in m.get("message", {}).get("content", []):
            if c.get("type") == "tool_use" and c.get("name") == "Bash":
                cmd = c.get("input", {}).get("command", "")
                for pat in ("git push", "git reset --hard", "git clean", "git checkout -- ", "rm -rf /", "rm -rf ~"):
                    if pat in cmd: bad.append(cmd[:120])
s["destructive"] = bad
# engine state
if engine == "hs":
    runs = sorted(glob.glob(os.path.join(wt, ".happysquad", "runs", "*", "state.json")))
    if runs:
        st = json.load(open(runs[-1])); evs = [json.loads(x) for x in open(os.path.join(os.path.dirname(runs[-1]), "events.jsonl")) if x.strip()]
        s.update({"state": st["state"], "iterations": st["iteration"], "dispatches": sum(1 for e in evs if e["event"] == "dispatch"),
                  "cause": st.get("block_cause"), "coverage": st.get("verified_coverage")})
else:
    p = os.path.join(wt, ".happysquad", "state.json")
    if os.path.isfile(p):
        st = json.load(open(p)); hist = st.get("history", [])
        s.update({"state": st.get("current_state"), "iterations": st.get("iteration"),
                  "dispatches": sum(1 for h in hist if h.get("state") in ("ARCHITECT", "IMPLEMENT", "PARALLEL_IMPLEMENT", "TEST", "PARALLEL_TEST", "REVIEW", "INNER_FIX")),
                  "history_len": len(hist)})
        rv = [h for h in hist if h.get("state") == "REVIEW"]
        s["reviews"] = [(h.get("verdict"), h.get("next")) for h in rv]
# files changed vs base (excluding .happysquad)
diff = subprocess.run(["git", "diff", "--name-only", base, "--", ".", ":(exclude).happysquad"], cwd=wt, capture_output=True, text=True).stdout.split()
untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--", ".", ":(exclude).happysquad"], cwd=wt, capture_output=True, text=True).stdout.split()
s["files_changed"] = sorted(set(diff) | set(untracked))
json.dump(s, open(os.path.join(out, "summary.json"), "w"), indent=2)
print("SUMMARY", json.dumps({k: s.get(k) for k in ("task", "engine", "state", "iterations", "dispatches", "asks", "destructive", "cost_usd", "turns", "secs", "oracle", "coverage")}))
PY

if [ "$KEEP" = 1 ]; then echo "kept: $WT"; else git -C "$PLUGIN" worktree remove --force "$WT" >/dev/null 2>&1 || rm -rf "$WT"; fi
