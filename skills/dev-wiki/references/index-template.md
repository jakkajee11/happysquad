# Wiki Index Template

Use this format for `knowledge/wiki/index.md`. The index is the global catalog of every wiki article, grouped by topic, with a one-line summary and the article's Updated date. It is auto-maintained by Ingest, Archive (from Query), and Lint operations.

## Format

```markdown
# Knowledge Base Index

## <Topic Name>

<Optional one-line description of the topic — included only when the topic section was just created.>

- [<Article Title>](<topic-slug>/<article>.md) — <one-line summary> · Updated <YYYY-MM-DD>
- [<Article Title>](<topic-slug>/<article>.md) — <one-line summary> · Updated <YYYY-MM-DD>

## <Another Topic Name>

- [<Article Title>](<topic-slug>/<article>.md) — <one-line summary> · Updated <YYYY-MM-DD>
- [Archive: <Query Topic>](<topic-slug>/<archive-slug>.md) — [Archived] <one-line summary> · Updated <YYYY-MM-DD>
```

## Field rules

- **Heading** — always `# Knowledge Base Index`. No subtitle, no other H1s.
- **Topic sections** — one `## <Topic Name>` per topic directory under `knowledge/wiki/`. Title Case for the visible heading; directory itself is kebab-case. Sort topics alphabetically.
- **Topic description** — one line, plain (no italics), included only on topic creation. Lint does not enforce or remove it.
- **Article entries** — one bullet per article. Format is fixed:
  - `- [Title](relative/path.md) — summary · Updated YYYY-MM-DD`
  - Em dash (`—`) separates link from summary.
  - Middle dot (`·`) separates summary from the Updated marker.
  - Sort articles alphabetically by title within each topic.
  - Paths are **relative to `knowledge/wiki/index.md`**, not project root — a link to `knowledge/wiki/<topic>/<article>.md` is written as `<topic>/<article>.md`.
- **Summary** — pulled from the article's lead paragraph; aim for under 120 characters. Use `(no summary)` when Lint adds a missing entry it cannot summarize.
- **Updated** — comes from the article's frontmatter `updated:` field. Lint falls back to file mtime only when the frontmatter field is absent.
- **Archive entries** — prefix the summary with `[Archived]`. Title may use the `Archive: <Topic>` convention.
- **Missing files** — Lint marks the entry as `[MISSING]` rather than deleting:
  - `- [Old Article](archive/old.md) — [MISSING] previously summarized X · Updated 2026-02-10`

## Default topics for happysquad

The default taxonomy below is what the skill creates on first ingest. Project teams can extend it but should keep the list short:

```markdown
# Knowledge Base Index

## Decisions

ADR-style records of architectural and product decisions, including alternatives considered.

## Lessons

Rules learned from BLOCKED reports and recurring reviewer issues — captured so the next loop avoids the same mistake.

## Patterns

Recurring technical patterns (caching, retries, error handling, idempotency, …) and where they're used in the project.

## Runbook

Operational procedures: deploy, rollback, oncall, debugging playbooks.

## Subsystems

Knowledge about specific subsystems / modules — architecture, contracts, known issues, test coverage.
```

When a topic section is first created, the optional one-line description above goes under it. Later articles drop in as bullets.

## Example (after a few ingests)

```markdown
# Knowledge Base Index

## Decisions

ADR-style records of architectural and product decisions, including alternatives considered.

- [API Key Prefix Format](decisions/api-key-prefix-format.md) — chose `sk_live_<32-hex>` over UUID-v7 for ops legibility · Updated 2026-05-20
- [Async Export Job Architecture](decisions/async-export-job-architecture.md) — picked job table + worker over message queue for simplicity at current scale · Updated 2026-05-18

## Lessons

Rules learned from BLOCKED reports and recurring reviewer issues — captured so the next loop avoids the same mistake.

- [Constant-Time Secret Comparison](lessons/constant-time-secret-comparison.md) — never compare API keys / tokens with `==` · Updated 2026-05-20
- [Migration Backfill Before Read-Flip](lessons/migration-backfill-before-read-flip.md) — adding a NOT NULL column requires a separate backfill stage · Updated 2026-04-30

## Patterns

- [Idempotency Keys](patterns/idempotency-keys.md) — client-supplied keys deduplicate retries safely · Updated 2026-05-20

## Subsystems

- [API Key Authentication](subsystems/api-key-authentication.md) — billing service auth via per-tenant API keys with constant-time validation · Updated 2026-05-20
- [Archive: Auth Flow Comparison](subsystems/auth-flow-comparison.md) — [Archived] synthesis of session vs API-key vs OAuth tradeoffs for this codebase · Updated 2026-05-12
```

## Notes

- The index is the single source of truth for "what's in the wiki." Every article must have an index entry; every index entry must point to an existing file (or be marked `[MISSING]`).
- No free-form prose between topic sections. The index is structured data the Lint check parses.
- Alphabetical ordering keeps merges deterministic.
- In Obsidian, pin `knowledge/wiki/index.md` as the default startup file for one-click navigation.
