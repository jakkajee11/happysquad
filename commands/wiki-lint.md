---
description: Run wiki quality checks — deterministic auto-fixes (index consistency, internal links, raw references, see-also pruning) plus heuristic findings reported for human review.
---

Load the `dev-wiki` skill at `${CLAUDE_PLUGIN_ROOT}/skills/dev-wiki/SKILL.md` and execute the Lint operation.

Steps:

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/bin/hs" wiki lint` and parse its one JSON line.
   - `{"ok": false, "error": "no wiki — run /wiki-ingest first"}` → tell the user and stop.
   - Otherwise this already did the deterministic pass (index consistency, internal links, raw:
     references, See Also pruning) and wrote its own `knowledge/wiki/log.md` entry. Its `fixes` are
     what got auto-fixed; its `reports` are broken/ambiguous links it couldn't resolve on its own —
     carry those into step 3 as findings, don't re-derive them.

2. **Heuristic report pass** — LLM judgement, do not auto-fix; surface findings:
   - Factual contradictions across articles (same claim, different conclusions, no Conflicts annotation).
   - Outdated claims superseded by newer ingests.
   - Missing conflict annotations where sources disagree.
   - Orphan pages with no inbound links from other wiki articles.
   - Missing cross-topic references.
   - Concepts frequently mentioned across articles but lacking a dedicated page.
   - Archive pages whose cited source articles have been substantially updated since archival.

3. Report to the user:
   - **Auto-fixed** — from the `hs wiki lint` JSON's `fixes`: count + brief list (e.g. "fixed 3 broken internal links, added 2 missing index entries").
   - **Findings (no auto-fix)** — the JSON's `reports`, plus the heuristic findings from step 2. List each with article path, type of issue, and one-line description. Don't make the user dig.
   - **Suggested next steps** — e.g. "consider creating `patterns/idempotency-keys.md` — mentioned in 4 articles but no dedicated page".

Lint never deletes content. It marks, fixes paths, and reports.
