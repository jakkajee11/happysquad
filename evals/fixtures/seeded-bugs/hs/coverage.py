"""Coverage report parsers (spec §7.2). Returns {"status", "total", "per_file", "lines"}.

status: ok | missing | unsupported | unparseable
lines:  {file: {lineno: hits}} when the format carries per-line data (lcov, cobertura); {} otherwise.
"""
import json
import os
import xml.etree.ElementTree as ET


def _pct(hit, found):
    return round(100.0 * hit / found, 2) if found else 100.0


def parse_lcov(path):
    per, lines, tf, th, cur, lf, lh = {}, {}, 0, 0, None, 0, 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("SF:"):
                cur, lf, lh = line[3:], 0, 0
                lines[cur] = {}
            elif line.startswith("DA:") and cur is not None:
                ln, hits = line[3:].split(",")[:2]
                lines[cur][int(ln)] = int(hits)
            elif line.startswith("LF:"):
                lf = int(line[3:])
            elif line.startswith("LH:"):
                lh = int(line[3:])
            elif line == "end_of_record" and cur is not None:
                if not lf and lines[cur]:
                    lf = len(lines[cur]); lh = sum(1 for h in lines[cur].values() if h > 0)
                per[cur] = _pct(lh, lf)
                tf += lf
                th += lh
                cur = None
    if not per:
        raise ValueError("no SF records")
    return {"status": "ok", "total": _pct(th, tf), "per_file": per, "lines": lines}


def parse_cobertura(path):
    root = ET.parse(path).getroot()
    if root.tag != "coverage" or "line-rate" not in root.attrib:
        raise ValueError("not cobertura")
    per, lines = {}, {}
    for cls in root.iter("class"):
        fn = cls.get("filename")
        ls = cls.find("lines")
        if fn is None or ls is None:
            continue
        found = hit = 0
        lines.setdefault(fn, {})
        for ln in ls.findall("line"):
            n = int(ln.get("number", "0")); h = int(ln.get("hits", "0"))
            lines[fn][n] = h
            found += 1
            if h > 0:
                hit += 1
        per[fn] = _pct(hit, found)
    return {"status": "ok", "total": round(float(root.get("line-rate")) * 100, 2), "per_file": per, "lines": lines}


def parse_istanbul_summary(data):
    per = {}
    for k, v in data.items():
        if k == "total":
            continue
        per[k] = float(v["lines"]["pct"])
    return {"status": "ok", "total": float(data["total"]["lines"]["pct"]), "per_file": per, "lines": {}}


def parse_pytest_cov(data):
    per = {k: float(v["summary"]["percent_covered"]) for k, v in data.get("files", {}).items()}
    return {"status": "ok", "total": float(data["totals"]["percent_covered"]), "per_file": per, "lines": {}}


def parse(path):
    if not path or not os.path.isfile(path):
        return {"status": "missing", "total": None, "per_file": {}, "lines": {}}
    name = os.path.basename(path).lower()
    try:
        if name.endswith(".info") or name == "lcov":
            return parse_lcov(path)
        if name.endswith(".xml"):
            return parse_cobertura(path)
        if name.endswith(".json"):
            with open(path) as f:
                data = json.load(f)
            if "total" in data and isinstance(data["total"], dict) and "lines" in data["total"]:
                return parse_istanbul_summary(data)
            if "totals" in data and "percent_covered" in data.get("totals", {}):
                return parse_pytest_cov(data)
            return {"status": "unsupported", "total": None, "per_file": {}, "lines": {}}
    except (ValueError, KeyError, ET.ParseError, json.JSONDecodeError, TypeError):
        return {"status": "unparseable", "total": None, "per_file": {}, "lines": {}}
    return {"status": "unsupported", "total": None, "per_file": {}, "lines": {}}


def _match_key(per, f, root):
    for k in per:
        kk = os.path.relpath(k, root) if os.path.isabs(k) else k
        if kk == f or kk.endswith("/" + f) or f.endswith("/" + kk) or os.path.normpath(kk) == os.path.normpath(f):
            return k
    return None


def per_file_for(cov, files, root):
    """Match per-file entries to the given repo-relative files (report may use absolute paths)."""
    per = cov.get("per_file") or {}
    return {f: (per[k] if (k := _match_key(per, f, root)) is not None else None) for f in files}


def delta_for(cov, files, root, added_by_file):
    """Coverage of lines ADDED in this change, per file (spec §20 delta rule).

    added_by_file: {file: set(lineno)} from the diff. Returns {file: pct | None}; None = no per-line
    data for a modified file (caller reports unverified). A file whose added lines contain no executable
    line counts as 100.
    """
    lines = cov.get("lines") or {}
    per = cov.get("per_file") or {}
    out = {}
    for f in files:
        k = _match_key(lines, f, root)
        added = added_by_file.get(f, set())
        if k is not None:
            execu = [n for n in added if n in lines[k]]
            if not execu:
                out[f] = 100.0
            else:
                hit = sum(1 for n in execu if lines[k][n] > 0)
                out[f] = _pct(hit, len(execu))
            continue
        # no per-line data: a brand-new file is fully "added", so its file percent is the delta
        pk = _match_key(per, f, root)
        out[f] = per[pk] if (pk is not None and added_by_file.get(f) == "all") else None
    return out
