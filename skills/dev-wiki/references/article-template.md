# Wiki Article Template

Use this format for every compiled article under `knowledge/wiki/<topic>/<article>.md` (excluding `index.md`, `log.md`, and archive pages — archives have their own template).

Articles are LLM-owned: rewrite, restructure, and synthesize freely as new sources arrive. The Sources and Raw fields are the audit trail back to the original material in `knowledge/raw/`.

## File naming

- `knowledge/wiki/<topic>/<concept-slug>.md`
- File name reflects the **concept**, not the raw source file.
- kebab-case, no date prefix.

## Format

```markdown
---
title: <Article title — concept name, not source title>
topic: <Matches parent directory, e.g., "subsystems">
sources: <Author or org + date>; <Author or org + date>; ...
raw: [<descriptive-name>](../../raw/<topic>/<file>.md); [<descriptive-name>](../../raw/<topic>/<file>.md)
related_runs: <Optional comma-separated happysquad run-ids that fed this article>
updated: <YYYY-MM-DD — date the article's knowledge content last changed>
tags: <Optional comma-separated tags; omit if none>
---

# <Article title>

<Lead paragraph: what this article is about, in two or three sentences.
Should stand alone as a summary if a reader stops here.>

## <Section heading>

<Body content. Synthesize across all cited sources. Use prose, lists, and
code blocks as appropriate. Cite specific claims inline by source name when
attribution matters: "design 20260520-103045 (architecter)".>

## <Another section>

<More body content.>

## Conflicts

<Optional. Use this section when sources disagree on a material claim.
Format: "On <topic>, <Source A> claims X; <Source B> claims Y." Cross-link
to the related article(s) carrying the other side of the disagreement.>

## See Also

- [Related Article](../<topic>/<other-article>.md) — one-line description
- [Cross-Topic Article](../<other-topic>/<article>.md) — one-line description
```

## Topic-specific section conventions

Different wiki topics warrant different default sections. Use these as starting structures, not as rigid templates:

**`subsystems/<name>.md`** — knowledge about a subsystem:
- Lead: what the subsystem does, where it lives in the repo.
- ## Architecture — components, contracts, data model
- ## Patterns in use — caching, error handling, retries, etc.
- ## Tests & coverage — what's tested how, known gaps
- ## Known issues — recurring bugs, performance pitfalls
- ## See Also

**`patterns/<name>.md`** — a recurring technical pattern:
- Lead: what the pattern is, when to use it.
- ## When to use
- ## When NOT to use
- ## Implementation notes
- ## Where it's used in this project — links to subsystem articles
- ## See Also

**`decisions/<slug>.md`** — ADR-style record (from brainstorm consensus or major design):
- Lead: the decision and one-line rationale.
- ## Context — why we needed to decide this
- ## Decision — what we chose
- ## Alternatives considered — what we rejected and why (from dissenting signoffs)
- ## Consequences — what this enables, what it forecloses
- ## Status — proposed | accepted | superseded-by-[link]

**`lessons/<slug>.md`** — a rule learned from BLOCKED or repeated review issues:
- Lead: one-sentence rule. Bold it.
- ## Why — the incident or pattern that produced this rule
- ## How to apply — where/when this kicks in
- ## Detection — how the reviewer / tester catches violations
- ## See Also — the BLOCKED.md or review.md sources this came from

**`runbook/<slug>.md`** — operational procedure:
- Lead: when to run this, expected outcome.
- ## Preconditions
- ## Steps (numbered, copy-pasteable)
- ## Verification — how to confirm success
- ## Rollback — if it goes wrong
- ## See Also

## Field rules

- **sources** — semicolon-separated. Each entry is "Author or organization + date" (e.g., `happysquad architecter 2026-05-20`; `Stripe Engineering 2025-09`). When the same author appears multiple times, list each instance with its own date.
- **raw** — semicolon-separated markdown links. Each link must point to an existing file under `knowledge/raw/<topic>/`. Path is relative to `knowledge/wiki/<topic>/`, so it is `../../raw/<topic>/<file>.md`.
- **related_runs** — optional. Lists the happysquad run-ids or session-ids that contributed to this article. Useful for tracing wiki content back to the runs that produced it.
- **updated** — refresh whenever the article's knowledge content materially changes. Do NOT update for cosmetic edits.
- **topic** — must match the parent directory name. Lint uses this to detect misfiled articles.

## Link style

Always use standard markdown links: `[Title](relative/path.md)`. Never `[[wikilinks]]`. Obsidian renders both, but the former works in every other renderer too.

## Example

```markdown
---
title: API Key Authentication
topic: subsystems
sources: happysquad architecter 2026-05-20; happysquad reviewer 2026-05-20; Stripe Engineering 2025-09
raw: [add-auth-design](../../raw/designs/2026-05-20-20260520-103045-add-auth-design.md); [add-auth-review](../../raw/reviews/2026-05-20-20260520-103045-add-auth-review.md); [stripe-idempotency](../../raw/patterns/2025-09-12-idempotency-keys-at-scale.md)
related_runs: 20260520-103045-add-auth
updated: 2026-05-20
tags: auth, api-keys, multi-tenant
---

# API Key Authentication

The billing service authenticates non-interactive callers with per-tenant API keys (`sk_live_<32-hex>`). Keys are validated against `tenants_api_keys` on every request and bound to a tenant_id for downstream authz. The implementation prioritizes constant-time comparison and avoids logging the raw key.

## Architecture

The middleware layer (`src/middleware/auth.ts`) extracts the `Authorization: Bearer <key>` header, hashes the key with SHA-256, and looks it up in `tenants_api_keys.key_hash`. A hit returns the bound `tenant_id` into request context; a miss returns 401 with no body...

## Patterns in use

- Constant-time comparison via `crypto.timingSafeEqual` ([Stripe's idempotency post](../../raw/patterns/2025-09-12-idempotency-keys-at-scale.md) influenced this choice).
- Key rotation supported by allowing two active keys per tenant during a 24h grace window.

## Known issues

- Run `20260520-103045-add-auth` review flagged a near-miss where keys were initially compared with `==`. Captured as [Lesson: constant-time secret comparison](../lessons/constant-time-secret-comparison.md).

## See Also

- [Lesson: constant-time secret comparison](../lessons/constant-time-secret-comparison.md)
- [Decision: API key prefix format](../decisions/api-key-prefix-format.md)
```

## Notes

- Keep the lead paragraph short and dense — index entries pull their summary from this.
- Use H2 (`##`) for major sections. Avoid H3+ unless an article truly needs deep nesting.
- `Conflicts` and `See Also` are omitted when empty. Don't write empty placeholders.
- Articles can mix happysquad raw sources and external raw sources freely. That's the point — internal knowledge cross-pollinates with external best practices.
