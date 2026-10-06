"""Effective config = embedded defaults + .happysquad/config.json (spec §16)."""
import copy
import json
import os
import sys

DEFAULTS = {
    "driver": "agent-tool",
    "cap": 5,
    "inner_cap": 2,
    "gate_retries": 1,
    "validation_retries": 2,
    "gate_timeout": 600,
    "coverage_threshold": 80,
    "coverage_rule": "delta",  # delta = lines added by the change; file = whole-file percent
    "review_mode": "split-on-risk",
    "max_parallel": 4,
    "models": {
        "architecter": "opus",
        "implementer": "sonnet",
        "tester": "sonnet",
        "reviewer": "opus",
        "specialist": "opus",
        "product": "opus",
    },
    "lite": {"auto": True, "cap": 3},
    "escalation": {"model": None},  # spec §8.6: one fix round on this model when a blocker is seen a 3rd time
    "checkpoint": {"enabled": True, "iterations": 3, "dispatches": 12},  # spec §8.9: agent-tool driver hand-off point
    "build_cmd": None,
    "test_cmd": None,
    "coverage_report": None,
    "redgreen_cmd": None,  # template with {file}; default "<test_cmd> {file}"
    # --fail-on-empty-test-suite: phpunit exits 1 when --filter matches nothing — a verify the reviewer
    # writes with it must stay trusted, or a fixed blocker reads "untrusted" and re-routes forever
    "allowed_flags": ["--run", "--filter", "--grep", "-t", "-k", "--testNamePattern", "--coverage",
                      "--fail-on-empty-test-suite"],
    "generated": ["**/pnpm-lock.yaml", "**/package-lock.json", "**/yarn.lock", "**/__snapshots__/**"],
    "headless": {
        "budget_per_phase": 2.0,
        "allowed_tools": "Read,Write,Edit,Grep,Glob,Bash",
        "disallowed_tools": [
            "Bash(git push:*)", "Bash(git reset:*)", "Bash(git clean:*)", "Bash(git checkout:*)",
            "Bash(git commit:*)", "Bash(rm -rf:*)", "Bash(curl:*)", "Bash(wget:*)", "Bash(sudo:*)", "Bash(gh:*)",
        ],
        "isolate": "worktree",
        "worktree_dir": None,  # default: <repo-parent>/<repo-name>-hs-wt/<run-id>; never under .git/
        "poll_interval": 3,
    },
    "hooks": {"stop_progress_nudge": False},
    "wiki": {"offer": True},
    "fleet": {"base_branch": None},
}

# keys accepted but ignored: the engine never asks a question (spec Q8), so `interactive` has no meaning
_RETIRED = ("interactive",)

# keys whose value is a dict merged one level deep rather than replaced
_NESTED = ("models", "lite", "escalation", "checkpoint", "headless", "hooks", "wiki", "fleet")

_warned = False


def config_path(root):
    return os.path.join(root, ".happysquad", "config.json")


def load(root, warn=True):
    """Return the effective config for repo `root`. Unknown keys warn once on stderr."""
    global _warned
    cfg = copy.deepcopy(DEFAULTS)
    path = config_path(root)
    if not os.path.isfile(path):
        return cfg
    with open(path) as f:
        user = json.load(f)
    unknown = []
    for k, v in user.items():
        if k in _RETIRED:
            continue  # accepted for backward compatibility, no effect
        if k not in DEFAULTS:
            unknown.append(k)
            continue
        if k in _NESTED and isinstance(v, dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    if unknown and warn and not _warned:
        _warned = True
        sys.stderr.write("hs: unknown config keys ignored: %s\n" % ", ".join(sorted(unknown)))
    return cfg
