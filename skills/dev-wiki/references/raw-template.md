# Raw Source Template

Use this format for every file written under `knowledge/raw/<topic>/`. Files in `knowledge/raw/` are immutable source material — preserve the original text verbatim, only cleaning formatting noise (excess whitespace, broken markdown, scraping artifacts). Never paraphrase, summarize, or rewrite the original.

## File naming

- `knowledge/raw/<topic>/YYYY-MM-DD-<descriptive-slug>.md` when the source has a clear date (today's date for happysquad artifacts; the article's publish date for external sources).
- `knowledge/raw/<topic>/<descriptive-slug>.md` when no date is appropriate (omit the date prefix only).
- For happysquad artifacts, the slug includes the run-id or session-id: e.g., `2026-05-20-20260520-103045-add-auth-design.md`.
- Slug: kebab-case, ≤60 characters.
- Collision: append numeric suffix (`<slug>-2.md`).

## Format

```markdown
---
title: <Original source title or happysquad artifact title>
source: <URL, file path, or other identifier — for happysquad: ".happysquad/runs/<run-id>/design.md">
kind: <one of: happysquad-design | happysquad-implementation | happysquad-test-report | happysquad-review | happysquad-blocked | happysquad-consensus | happysquad-signoffs | external-article | external-doc | pasted>
author: <Author name(s), comma-separated; or "happysquad" for internal artifacts; or "Unknown">
publication: <Publication / site name; or "Unknown"; omit for happysquad artifacts>
published: <YYYY-MM-DD or "Unknown" — for happysquad artifacts use the run/session start date>
collected: <YYYY-MM-DD — today's date when this raw file was created>
topic: <Matches parent directory under knowledge/raw/>
run_id: <Only for happysquad artifacts: the source run-id or session-id>
tags: <Optional, comma-separated; omit if none>
---

# <Original source title>

<Optional one-line attribution: byline, run-id, etc.>

<Original body text. Preserve headings, lists, code blocks, blockquotes.
Do NOT paraphrase. Clean only formatting artifacts.>
```

## Examples

### Happysquad design artifact

```markdown
---
title: API key authentication design (run 20260520-103045-add-auth)
source: .happysquad/runs/20260520-103045-add-auth/design.md
kind: happysquad-design
author: happysquad
published: 2026-05-20
collected: 2026-05-20
topic: designs
run_id: 20260520-103045-add-auth
tags: auth, api-keys, multi-tenant
---

# API key authentication design

<copied verbatim from the design.md, including its Task Summary, Scope, Acceptance Criteria, etc.>
```

### External article

```markdown
---
title: Idempotency keys at scale
source: https://stripe.com/blog/idempotency
kind: external-article
author: Stripe Engineering
publication: stripe.com
published: 2025-09-12
collected: 2026-05-20
topic: patterns
tags: idempotency, api-design
---

# Idempotency keys at scale

By Stripe Engineering · September 2025

<rest of original article text>
```

### Brainstorm consensus

```markdown
---
title: Customer data export brainstorm consensus (session bs-export-user-data)
source: .happysquad/brainstorms/20260520-114500-bs-export-user-data/consensus.md
kind: happysquad-consensus
author: happysquad
published: 2026-05-20
collected: 2026-05-20
topic: brainstorms
run_id: 20260520-114500-bs-export-user-data
tags: exports, gdpr, async-jobs
---

# Customer data export brainstorm consensus

<copied verbatim from consensus.md>
```

## Notes

- The `kind` field is what lets the skill route the compile step automatically. Don't omit it.
- For happysquad artifacts, `author: happysquad` is canonical — the individual agent names (architecter, reviewer, etc.) appear in the body, not in metadata.
- If the source is paste-only (no URL or path), use `source: pasted-by-user` and `kind: pasted`.
- Frontmatter renders cleanly in Obsidian's properties panel and is trivially parseable by `grep` / `yq` for users who don't use Obsidian.
