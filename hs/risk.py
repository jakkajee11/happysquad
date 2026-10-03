"""Risk detection (spec §7.6): regex patterns over changed paths and added diff lines → axes."""
import fnmatch
import json
import os
import re
import subprocess

from . import gitutil

PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def load_patterns(root):
    base = json.load(open(os.path.join(PLUGIN_ROOT, "references", "risk-patterns.json")))
    base.pop("_doc", None)
    user = os.path.join(root, ".happysquad", "risk-patterns.json")
    if os.path.isfile(user):
        u = json.load(open(user))
        u.pop("_doc", None)
        for axis, spec in u.items():
            base.setdefault(axis, {})
            for k, v in spec.items():
                base[axis][k] = v  # a user key replaces the default key wholesale ([] disables)
    return base


def added_lines(root, base_ref, path):
    """Text of lines added vs base_ref for one path (whole file when untracked/new)."""
    if base_ref:
        p = subprocess.run(["git", "diff", "-U0", base_ref, "--", path], cwd=root, capture_output=True, text=True)
        if p.returncode == 0 and p.stdout:
            return [l[1:] for l in p.stdout.splitlines() if l.startswith("+") and not l.startswith("+++")]
    fp = os.path.join(root, path)
    if os.path.isfile(fp):
        try:
            with open(fp, errors="replace") as f:
                return f.read().splitlines()
        except OSError:
            return []
    return []


def detect(root, base_ref, files=None, patterns=None):
    pats = patterns or load_patterns(root)
    files = files if files is not None else gitutil.changed_files(root, base_ref)
    matches = []
    for path in files:
        added = None
        for axis, spec in pats.items():
            for rx in spec.get("paths", []):
                if re.search(rx, path):
                    matches.append({"file": path, "axis": axis, "kind": "path", "pattern": rx})
                    break
            for g in spec.get("manifests", []):
                if fnmatch.fnmatch(os.path.basename(path), g):
                    matches.append({"file": path, "axis": axis, "kind": "manifest", "pattern": g})
                    break
            if spec.get("diff"):
                if added is None:
                    added = added_lines(root, base_ref, path)
                for rx in spec["diff"]:
                    crx = re.compile(rx)
                    hit = next((l for l in added if crx.search(l)), None)
                    if hit is not None:
                        matches.append({"file": path, "axis": axis, "kind": "diff", "pattern": rx, "line": hit.strip()[:120]})
                        break
    axes = sorted({m["axis"] for m in matches})
    return {"base_ref": base_ref, "files": files, "axes": axes, "matches": matches}
