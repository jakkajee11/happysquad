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
EXPECT="$(python3 -c "import json,sys,os;p=os.path.join('$HERE','scenarios','$SCEN.json');print(json.load(open(p)).get('_expect','COMPLETE') if os.path.isfile(p) else 'COMPLETE')")"

WORK="$(mktemp -d /tmp/hs-fake-XXXXXX)"
cp -R "$HERE/fixtures/toy-repo/." "$WORK/"
cd "$WORK"
git init -q && git add -A && git -c user.email=t@t -c user.name=t commit -qm init
export HS_TOY_FAST=1
"$HS" init >/dev/null
cat > .happysquad/config.json <<EOF
{"build_cmd":"npm run build","test_cmd":"npm test","coverage_report":"coverage/lcov.info","redgreen_cmd":"npm test -- {file}","interactive":false,"cap":3}
EOF

act="$("$HS" run start "add mul(a,b) to calc" --driver fake)"
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
    wait)
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
