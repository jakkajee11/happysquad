#!/usr/bin/env python3
"""Fake `claude` binary for the headless driver: accepts claude's argv, runs fake_agent.py.

Reads: -p <prompt>, --agent <name>. Everything else is accepted and ignored. The scenario comes
from FAKE_SCENARIO (default pass-first). Prints a claude-like JSON result line.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    argv = sys.argv[1:]
    prompt = agent = None
    i = 0
    while i < len(argv):
        if argv[i] == "-p":
            prompt = argv[i + 1]; i += 2
        elif argv[i] == "--agent":
            agent = argv[i + 1]; i += 2
        elif argv[i] in ("--agents", "--model", "--permission-mode", "--allowedTools", "--max-budget-usd",
                         "--output-format", "--disallowedTools", "--append-system-prompt"):
            i += 2
        else:
            i += 1
    if prompt is None:
        print(json.dumps({"type": "result", "subtype": "error", "error": "no -p"})); sys.exit(2)
    # FAKE_HANG=<agent>: that agent never finishes, for the headless agent_timeout test
    if agent and os.environ.get("FAKE_HANG") == agent:
        import time
        time.sleep(3600)
    # the prompt names the out file; fake_agent wants the prompt as a file path
    m = re.search(r"`([^`]*out\.json)`", prompt)
    if not m:
        print(json.dumps({"type": "result", "subtype": "error", "error": "no out_file in prompt"})); sys.exit(2)
    out_file = m.group(1)
    pf = os.path.join(os.path.dirname(out_file), "prompt.rendered.md")
    os.makedirs(os.path.dirname(pf), exist_ok=True)
    with open(pf, "w") as f:
        f.write(prompt)
    rc = subprocess.run([sys.executable, os.path.join(HERE, "fake_agent.py"), pf, out_file,
                         "--scenario", os.environ.get("FAKE_SCENARIO", "pass-first")]).returncode
    print(json.dumps({"type": "result", "subtype": "success" if rc == 0 else "error", "agent": agent,
                      "total_cost_usd": 0.01, "num_turns": 1, "duration_ms": 1500}))
    sys.exit(rc)


if __name__ == "__main__":
    main()
