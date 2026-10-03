"""hs wiki lint — deterministic half of the dev-wiki Lint operation (spec v1.1 §13).

Checks index<->files consistency, resolves/reports broken internal + raw: links, and prunes
dead See Also bullets. The LLM (`/wiki-lint`) runs this first, then does the heuristic half
(contradictions, orphans, missing cross-refs) that needs judgment, not regexes.
"""
import datetime
import os
import re

from . import state as S

LINK_RE = re.compile(r'\[([^\]]*)\]\(([^)]+)\)')
ENTRY_RE = re.compile(
    r'^-\s+\[(?P<title>[^\]]+)\]\((?P<link>[^)]+)\)\s+—\s+(?P<summary>.*?)\s+·\s+Updated\s+(?P<updated>\d{4}-\d{2}-\d{2})\s*$')
FRONTMATTER_RE = re.compile(r'\A---\n(.*?\n)---\n', re.DOTALL)
SEE_ALSO_RE = re.compile(r'^## See Also\s*$')
BULLET_LINK_RE = re.compile(r'^-\s+\[([^\]]+)\]\(([^)]+)\)')


def _wiki_dir(root):
    return os.path.join(root, "knowledge", "wiki")


def _raw_dir(root):
    return os.path.join(root, "knowledge", "raw")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _frontmatter(text):
    """-> (fields dict, raw frontmatter block incl. fences, body). fields/block empty if none."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, "", text
    fields = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fields[k.strip()] = v.strip()
    return fields, m.group(0), text[m.end():]


def _title_of(text, fields):
    if fields.get("title"):
        return fields["title"]
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "(untitled)"


def _summary_of(body, limit=120):
    for para in body.split("\n\n"):
        para = para.strip()
        if not para or para.startswith("#"):
            continue
        s = " ".join(para.split())
        return s[:limit].rstrip() if len(s) > limit else s
    return None


def _topic_heading(topic_dir):
    return " ".join(w.capitalize() for w in re.split(r'[-_]+', topic_dir) if w)


def _wiki_articles(root):
    """{(topic_dir, filename): abspath} — one level under knowledge/wiki/, excluding index/log."""
    out = {}
    wiki = _wiki_dir(root)
    if not os.path.isdir(wiki):
        return out
    for entry in sorted(os.listdir(wiki)):
        d = os.path.join(wiki, entry)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".md"):
                out[(entry, fn)] = os.path.join(d, fn)
    return out


def _find_by_basename(search_root, basename):
    hits = []
    for dirpath, _dirs, files in os.walk(search_root):
        if basename in files:
            hits.append(os.path.join(dirpath, basename))
    return hits


def _try_fix_link(article_path, link, search_root):
    """Target of `link` is missing; search search_root by basename. -> (new_link, None) | (None, n_hits)."""
    hits = _find_by_basename(search_root, os.path.basename(link))
    if len(hits) == 1:
        rel = os.path.relpath(hits[0], os.path.dirname(article_path))
        return rel.replace(os.sep, "/"), None
    return None, len(hits)


# --- 1. index consistency ----------------------------------------------------

def _norm_link(link):
    return os.path.normpath(link).replace(os.sep, "/")


def _parse_index(text):
    lines = text.splitlines()
    preamble, sections, i = [], [], 0
    while i < len(lines) and not lines[i].startswith("## "):
        preamble.append(lines[i])
        i += 1
    cur = None
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            cur = {"heading": line[3:].strip(), "desc": [], "entries": []}
            sections.append(cur)
        else:
            m = ENTRY_RE.match(line)
            if m:
                cur["entries"].append({"title": m["title"], "link": m["link"],
                                        "summary": m["summary"], "updated": m["updated"]})
            elif cur is not None and line.strip():
                cur["desc"].append(line)
        i += 1
    return preamble, sections


def _render_index(preamble, sections):
    while preamble and preamble[-1] == "":
        preamble.pop()
    out = list(preamble)
    for sec in sorted(sections, key=lambda s: s["heading"].lower()):
        out.append("")
        out.append("## " + sec["heading"])
        if sec["desc"]:
            out.append("")
            out.extend(sec["desc"])
        if sec["entries"]:
            out.append("")
            for e in sorted(sec["entries"], key=lambda e: e["title"].lower()):
                out.append("- [%s](%s) — %s · Updated %s" % (e["title"], e["link"], e["summary"], e["updated"]))
    return "\n".join(out) + "\n"


def _lint_index(root, wiki, fixes):
    index_path = os.path.join(wiki, "index.md")
    index_text = _read(index_path)
    preamble, sections = _parse_index(index_text)

    indexed = {_norm_link(e["link"]) for sec in sections for e in sec["entries"]}

    for sec in sections:
        for e in sec["entries"]:
            target = os.path.normpath(os.path.join(wiki, e["link"]))
            if not os.path.isfile(target) and not e["summary"].startswith("[MISSING] "):
                e["summary"] = "[MISSING] " + e["summary"]
                fixes.append({"kind": "index-missing", "file": "knowledge/wiki/index.md",
                              "detail": "%s -> %s" % (e["title"], e["link"])})

    by_heading = {sec["heading"].lower(): sec for sec in sections}
    for (topic_dir, fn), path in sorted(_wiki_articles(root).items()):
        link = _norm_link("%s/%s" % (topic_dir, fn))
        if link in indexed:
            continue
        heading = _topic_heading(topic_dir)
        sec = by_heading.get(heading.lower())
        if sec is None:
            sec = {"heading": heading, "desc": [], "entries": []}
            sections.append(sec)
            by_heading[heading.lower()] = sec
        text = _read(path)
        fields, _block, body = _frontmatter(text)
        title = _title_of(text, fields)
        summary = _summary_of(body) or "(no summary)"
        updated = fields.get("updated") or datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat()
        sec["entries"].append({"title": title, "link": link, "summary": summary, "updated": updated})
        indexed.add(link)
        fixes.append({"kind": "index-add", "file": "knowledge/wiki/index.md", "detail": "%s (%s)" % (title, link)})

    new_text = _render_index(preamble, sections)
    return {index_path: new_text} if new_text != index_text else {}


# --- 2/3/4. links, raw refs, see-also pruning (per article) ------------------

def _process_line(line, article_path, search_root, rel_file, fix_kind, report_kind_broken, report_kind_ambiguous,
                   prune, fixes, reports):
    """Fix/report/prune every .md link in `line` resolved relative to article_path. None return = drop line."""
    new_line, drop = line, False
    for m in LINK_RE.finditer(line):
        link = m.group(2)
        if link.startswith(("http://", "https://")) or not link.endswith(".md"):
            continue
        target = os.path.normpath(os.path.join(os.path.dirname(article_path), link))
        if os.path.isfile(target):
            continue
        fixed, n = _try_fix_link(article_path, link, search_root)
        if fixed:
            new_line = new_line.replace("(%s)" % link, "(%s)" % fixed, 1)
            fixes.append({"kind": fix_kind, "file": rel_file, "detail": "%s -> %s" % (link, fixed)})
        elif prune:
            drop = True
            fixes.append({"kind": "see-also-prune", "file": rel_file,
                          "detail": "%s (%s)" % (m.group(1), link)})
        else:
            reports.append({"kind": report_kind_ambiguous if n > 1 else report_kind_broken,
                            "file": rel_file, "detail": link})
    return None if drop else new_line


def _lint_article(root, wiki, raw_root, topic_dir, fn, path, fixes, reports):
    rel_file = "knowledge/wiki/%s/%s" % (topic_dir, fn)
    text = _read(path)
    fields, fm_block, body = _frontmatter(text)
    changed = False

    raw_val = fields.get("raw")
    if raw_val:
        new_raw_val = raw_val
        for m in LINK_RE.finditer(raw_val):
            link = m.group(2)
            if link.startswith(("http://", "https://")):
                continue
            target = os.path.normpath(os.path.join(os.path.dirname(path), link))
            if os.path.isfile(target):
                continue
            fixed, n = _try_fix_link(path, link, raw_root)
            if fixed:
                new_raw_val = new_raw_val.replace("(%s)" % link, "(%s)" % fixed, 1)
                fixes.append({"kind": "raw-fix", "file": rel_file, "detail": "%s -> %s" % (link, fixed)})
            else:
                reports.append({"kind": "raw-ambiguous" if n > 1 else "raw-broken", "file": rel_file,
                                "detail": link})
        if new_raw_val != raw_val:
            fm_block, nsub = re.subn(r'(?m)^raw:.*$', "raw: " + new_raw_val, fm_block, count=1)
            changed = changed or bool(nsub)

    out_lines, in_see_also = [], False
    for line in body.split("\n"):
        if SEE_ALSO_RE.match(line):
            in_see_also = True
            out_lines.append(line)
            continue
        if line.startswith("## "):
            in_see_also = False
            out_lines.append(line)
            continue
        new_line = _process_line(line, path, wiki, rel_file, "link-fix", "link-broken", "link-ambiguous",
                                  in_see_also and bool(BULLET_LINK_RE.match(line)), fixes, reports)
        if new_line is None:
            changed = True
            continue
        changed = changed or new_line != line
        out_lines.append(new_line)

    if not changed:
        return None
    return fm_block + "\n".join(out_lines)


# --- entry point ---------------------------------------------------------------

def lint(root, dry_run=False):
    wiki = _wiki_dir(root)
    if not os.path.isfile(os.path.join(wiki, "index.md")):
        return {"ok": False, "error": "no wiki — run /wiki-ingest first"}

    fixes, reports, writes = [], [], {}
    writes.update(_lint_index(root, wiki, fixes))

    raw_root = _raw_dir(root)
    for (topic_dir, fn), path in sorted(_wiki_articles(root).items()):
        new_text = _lint_article(root, wiki, raw_root, topic_dir, fn, path, fixes, reports)
        if new_text is not None:
            writes[path] = new_text

    if not dry_run:
        for path, new_text in writes.items():
            S.atomic_write(path, new_text)
        log_path = os.path.join(wiki, "log.md")
        old_log = _read(log_path) if os.path.isfile(log_path) else "# Wiki Log\n"
        entry = "## [%s] lint | %d issues found, %d auto-fixed" % (
            S.now()[:10], len(fixes) + len(reports), len(fixes))
        S.atomic_write(log_path, old_log.rstrip("\n") + "\n\n" + entry + "\n")

    return {"ok": True, "issues": len(fixes) + len(reports), "fixed": len(fixes), "dry_run": dry_run,
            "fixes": fixes, "reports": reports}
