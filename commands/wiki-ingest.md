---
description: Ingest a source (happysquad artifact, URL, file path, or pasted content) into the wiki — copy to knowledge/raw/ verbatim, then synthesize into knowledge/wiki/ articles with cascade updates.
argument-hint: <path | url | --paste | --latest-run | --latest-brainstorm>
---

Load the `dev-wiki` skill at `${CLAUDE_PLUGIN_ROOT}/skills/dev-wiki/SKILL.md` and execute the Ingest operation.

Steps:

1. If `$ARGUMENTS` is empty, ask the user with AskUserQuestion what to ingest. Offer options: latest dev-loop run artifacts, latest brainstorm consensus, a specific file path, a URL, or pasted text.
2. If `$ARGUMENTS` is `--latest-run`, read `.happysquad/state.json`, find the most recent run-id, and queue these artifacts for ingest (in order): `design.md`, `review.md`, `BLOCKED.md` (if present), then `test-report.md` only if it contains lessons-worthy content.
3. If `$ARGUMENTS` is `--latest-brainstorm`, find the most recent session in `.happysquad/brainstorms/`, queue `consensus.md` and `signoffs.md`.
4. If `$ARGUMENTS` is `--paste`, ask the user to paste the content and the title/source attribution.
5. Otherwise treat `$ARGUMENTS` as a path or URL.
6. Initialize `knowledge/`, `knowledge/raw/`, `knowledge/wiki/`, `index.md`, `log.md` only if missing — never overwrite.
7. For each source in the queue:
   a. Identify `kind` (happysquad-design, happysquad-review, …, external-article, pasted) from the path or context.
   b. Fetch / copy content. For URLs, use the available web tool. For files outside `.happysquad/`, read directly. If unreachable, ask the user to paste.
   c. Write to `knowledge/raw/<topic>/YYYY-MM-DD-<slug>.md` per `references/raw-template.md`. Preserve content verbatim; clean only formatting noise.
   d. Decide compile destinations per the happysquad artifact mode table in the skill (e.g. `design.md` → `subsystems/<name>.md`; `BLOCKED.md` → `lessons/<slug>.md`).
   e. Compile or merge into the destination article(s) per `references/article-template.md`. Refresh `updated:` dates.
   f. Cascade — scan related articles, update materially affected ones, refresh their `updated:` dates.
8. Update `knowledge/wiki/index.md` with the new/updated entries per `references/index-template.md`.
9. Append a single log entry per ingest to `knowledge/wiki/log.md`:
   ```
   ## [YYYY-MM-DD] ingest | <primary article title>
   - Updated: <cascade-updated article>
   ```
10. Report back to the user:
    - Sources ingested (path → raw file)
    - Articles created or merged (with paths)
    - Cascade-updated articles (with paths)
    - One-line suggestion for the next operation (often `/wiki-ask` to verify the synthesis or `/wiki-lint` if many articles were touched)

Never overwrite a raw file. On slug collision, append a numeric suffix.

Never auto-write to the wiki from happysquad working files without explicit invocation of this command. The `/happysquad-loop` and `/brainstorm` commands surface an *offer* to ingest at the end of their run — accepting the offer dispatches this command.
