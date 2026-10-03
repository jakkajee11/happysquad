#!/usr/bin/env bash
# $0 end-to-end: drive hs through a full loop on a throwaway copy of the toy repo using fake_agent.py.
# Usage: evals/run_fake.sh [scenario] [--keep]
# Exit 0 when the run reaches COMPLETE (or the scenario's expected terminal status).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGIN="$(cd "$HERE/.." && pwd)"
HS="$PLUGIN/bin/hs"
SCEN="${1:-pass-first}"
KEEP="${2:-}"
RUN_FLAGS="${RUN_FLAGS:-}"
EXPECT="$(python3 -c "import json,sys,os;p=os.path.join('$HERE','scenarios','$SCEN.json');print(json.load(open(p)).get('_expect','COMPLETE') if os.path.isfile(p) else 'COMPLETE')")"

# Run every entry in a JSON array of {phase,prompt_file,out_file} under $1 whose out_file is
# not yet written, dispatching each through fake_agent.py and bumping $n. Used for dispatch_many
# (a parallel wave) and for a `wait` action that carries a `dispatches` list (an unfinished
# sibling in that same wave, or a validation-retry re-dispatch) — both are "agents to run now".
run_dispatch_list() {
  while IFS=$'\t' read -r ph pf of; do
    [ -z "$pf" ] && continue
    n=$((n+1))
    echo "[$n] dispatch $ph -> $of"
    python3 "$HERE/fake_agent.py" "$pf" "$of" --scenario "$SCEN"
  done < <(printf '%s' "$1" | python3 -c '
import json, os, sys
for e in (json.load(sys.stdin).get("dispatches") or []):
    if not os.path.isfile(e["out_file"]):
        print("%s\t%s\t%s" % (e["phase"], e["prompt_file"], e["out_file"]))
')
}

WORK="$(mktemp -d /tmp/hs-fake-XXXXXX)"
cp -R "$HERE/fixtures/toy-repo/." "$WORK/"
mkdir -p "$WORK/coverage"  # gitignored in the fixture; a fresh checkout (e.g. a worktree) lacks it and npm's lcov reporter errors ENOENT
cd "$WORK"
git init -q && git add -A && git -c user.email=t@t -c user.name=t commit -qm init
export HS_TOY_FAST=1
"$HS" init >/dev/null
cat > .happysquad/config.json <<EOF
{"build_cmd":"npm run build","test_cmd":"npm test","coverage_report":"coverage/lcov.info","redgreen_cmd":"npm test -- {file}","cap":3}
EOF
# RUN_CONFIG: a JSON object merged over the config above (e.g. '{"escalation":{"model":"opus-x"}}')
if [ -n "${RUN_CONFIG:-}" ]; then
  python3 - "$RUN_CONFIG" <<'PY2'
import json, sys
p = ".happysquad/config.json"; c = json.load(open(p)); c.update(json.loads(sys.argv[1])); json.dump(c, open(p, "w"))
PY2
fi

# --driver agent-tool (not "fake"): P1b repurposed --driver fake/headless to mean "hs drives a
# real/fake `claude -p` itself" (hs/drivers.py run_headless), which blocks until done and never
# surfaces the dispatch/wait steps this harness drives by hand with fake_agent.py. "agent-tool" is
# just a label on state.json ("driver"); it is never inspected by machine.py's dispatch logic.
act="$("$HS" run start "add mul(a,b) to calc" --driver agent-tool $RUN_FLAGS)"
n=0
while :; do
  kind="$(printf '%s' "$act" | python3 -c 'import json,sys;print(json.load(sys.stdin)["action"])')"
  case "$kind" in
    dispatch)
      n=$((n+1))
      pf="$(printf '%s' "$act" | python3 -c 'import json,sys;print(json.load(sys.stdin)["prompt_file"])')"
      of="$(printf '%s' "$act" | python3 -c 'import json,sys;print(json.load(sys.stdin)["out_file"])')"
      ph="$(printf '%s' "$act" | python3 -c 'import json,sys;print(json.load(sys.stdin)["phase"])')"
      echo "[$n] dispatch $ph -> $of"
      python3 "$HERE/fake_agent.py" "$pf" "$of" --scenario "$SCEN"
      act="$("$HS" advance)"
      ;;
    dispatch_many)
      run_dispatch_list "$act"
      act="$("$HS" advance)"
      ;;
    wait)
      has="$(printf '%s' "$act" | python3 -c 'import json,sys;print(1 if json.load(sys.stdin).get("dispatches") else 0)')"
      if [ "$has" = "1" ]; then run_dispatch_list "$act"; fi
      act="$("$HS" wait --timeout 300 --interval 0.5)"
      ;;
    advance)
      act="$("$HS" advance)"
      ;;
    done)
      status="$(printf '%s' "$act" | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])')"
      echo "DONE status=$status dispatches=$n"
      printf '%s\n' "$act"
      [ "$KEEP" = "--keep" ] && echo "kept: $WORK" || rm -rf "$WORK"
      [ "$status" = "$EXPECT" ] && exit 0 || { echo "expected $EXPECT"; exit 1; }
      ;;
    error)
      echo "ERROR: $act"; echo "kept: $WORK"; exit 2
      ;;
    *)
      echo "unexpected action: $act"; echo "kept: $WORK"; exit 2
      ;;
  esac
  [ $n -gt 40 ] && { echo "runaway"; exit 2; }
done
