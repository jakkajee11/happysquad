"""Coverage report parsers (spec §7.2). Returns {"status", "total", "per_file"}.

status: ok | missing | unsupported | unparseable
"""
import json
import os
import xml.etree.ElementTree as ET


def _pct(hit, found):
    return round(100.0 * hit / found, 2) if found else 100.0


def parse_lcov(path):
    per, tf, th, cur, lf, lh = {}, 0, 0, None, 0, 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("SF:"):
                cur, lf, lh = line[3:], 0, 0
            elif line.startswith("LF:"):
                lf = int(line[3:])
            elif line.startswith("LH:"):
                lh = int(line[3:])
            elif line == "end_of_record" and cur is not None:
                per[cur] = _pct(lh, lf)
                tf += lf
                th += lh
                cur = None
    if not per:
        raise ValueError("no SF records")
    return {"status": "ok", "total": _pct(th, tf), "per_file": per}


def parse_cobertura(path):
    root = ET.parse(path).getroot()
    if root.tag != "coverage" or "line-rate" not in root.attrib:
        raise ValueError("not cobertura")
    per = {}
    for cls in root.iter("class"):
        fn = cls.get("filename")
        lines = cls.find("lines")
        if fn is None or lines is None:
            continue
        found = hit = 0
        for ln in lines.findall("line"):
            found += 1
            if int(ln.get("hits", "0")) > 0:
                hit += 1
        per[fn] = _pct(hit, found)
    return {"status": "ok", "total": round(float(root.get("line-rate")) * 100, 2), "per_file": per}


def parse_istanbul_summary(data):
    per = {}
    for k, v in data.items():
        if k == "total":
            continue
        per[k] = float(v["lines"]["pct"])
    return {"status": "ok", "total": float(data["total"]["lines"]["pct"]), "per_file": per}


def parse_pytest_cov(data):
    per = {k: float(v["summary"]["percent_covered"]) for k, v in data.get("files", {}).items()}
    return {"status": "ok", "total": float(data["totals"]["percent_covered"]), "per_file": per}


def parse(path):
    if not path or not os.path.isfile(path):
        return {"status": "missing", "total": None, "per_file": {}}
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
            return {"status": "unsupported", "total": None, "per_file": {}}
    except (ValueError, KeyError, ET.ParseError, json.JSONDecodeError, TypeError):
        return {"status": "unparseable", "total": None, "per_file": {}}
    return {"status": "unsupported", "total": None, "per_file": {}}


def per_file_for(cov, files, root):
    """Match per-file entries to the given repo-relative files (report may use absolute paths)."""
    out = {}
    per = cov.get("per_file") or {}
    for f in files:
        hit = None
        for k, v in per.items():
            kk = k
            if os.path.isabs(kk):
                kk = os.path.relpath(kk, root)
            if kk == f or kk.endswith("/" + f) or f.endswith("/" + kk) or os.path.normpath(kk) == os.path.normpath(f):
                hit = v
                break
        out[f] = hit
    return out
