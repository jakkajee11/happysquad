---
name: dev-wiki
description: |
  Maintains a compounding project knowledge base for the happysquad, based on Andrej Karpathy's
  LLM-wiki pattern. State lives in `knowledge/raw/` (immutable ingested sources — designs, reviews,
  brainstorm consensuses, BLOCKED reports, tech summaries, external docs) and `knowledge/wiki/`
  (LLM-compiled articles organized by topic, cross-linked, cascade-updated). Triggers: ingest this
  into the wiki, add to project wiki, what do we know about X, what does the wiki say, archive this
  answer, lint the wiki, project wiki, LLM wiki, Karpathy wiki, /wiki-ingest, /wiki-ask, /wiki-lint.
  Auto-detects happysquad artifacts (.happysquad/runs/* and .happysquad/brainstorms/*) and extracts
  their structure on ingest. Distinct from .happysquad/ run state (per-task working files) and from
  any external KB sync.
---

# Happysquad Wiki

A compounding knowledge base for the squad's project. Designs, reviews, brainstorm consensuses, BLOCKED reports — every artifact the squad produces can be ingested as a raw source and synthesized into wiki articles that survive across runs. The wiki is the squad's institutional memory.

Based on [Andrej Karpathy's LLM-wiki pattern](https://karpathy.ai/posts/llm-wiki):
- "The LLM writes and maintains the wiki; the human reads and asks questions."
- "The wiki is a persistent, compounding artifact."

## Why a wiki in the squad

Without a wiki, every loop starts from a cold cache. The squad re-derives the same patterns, repeats the same architectural debates, and re-hits the same gotchas captured in last quarter's BLOCKED.md. The wiki turns one-off artifacts into reusable knowledge:

- The architecter reads `wiki/subsystems/<name>.md` before designing → faster, more consistent designs.
- The reviewer reads `wiki/lessons/<rule>.md` before flagging issues → catches recurring mistakes earlier.
- The product agent reads `wiki/decisions/<name>.md` before proposing scope → doesn't re-open settled questions.
- Humans reading the wiki via Obsidian (or any markdown editor) get a graph-view of the project's accumulated knowledge.

## Three operations

The skill exposes three operations triggered by separate commands:

| Operation | Command       | What it does                                                   |
|-----------|---------------|----------------------------------------------------------------|
| Ingest    | `/wiki-ingest` | Pull a source into `raw/`, then compile it into `wiki/` articles. |
| Query     | `/wiki-ask`    | Search the wiki and answer a question with citations.          |
| Lint      | `/wiki-lint`   | Deterministic auto-fixes plus heuristic findings.              |

Plus implicit operations:
- `/happysquad-loop` offers to ingest a finished run's `design.md` + `review.md` + `BLOCKED.md` (if any).
- `/brainstorm` offers to ingest a finished session's `consensus.md` + `signoffs.md`.

These offers are opt-in — the user always confirms before anything gets written to the wiki.

## Architecture

```
<repo root>/
├── .happysquad/                 # per-task working files (NOT wiki)
│   ├── runs/<run-id>/
│   └── brainstorms/<session-id>/
└── knowledge/                  # the wiki — clean, Obsidian-vault-friendly
    ├── raw/                    # immutable ingested sources
    │   └── <topic>/
    └── wiki/                   # compiled articles (LLM-owned)
        ├── index.md
        ├── log.md
        └── <topic>/
            └── <article>.md
```

The `.happysquad/` directory is operational; `knowledge/` is the wiki. Keep them separate — `.happysquad/` can be `.gitignore`d, `knowledge/` should be committed.

### Obsidian (recommended, optional)

Point an Obsidian vault at `knowledge/` (the parent of `raw/` and `wiki/`). You get graph view, backlinks, vault search. The skill never depends on Obsidian-specific syntax — all links are standard markdown `[Title](relative/path.md)`, never `[[wikilinks]]`. Works in any editor (VS Code, vim, GitHub web view).

### Initialization

Triggered only on the first Ingest. Create only what is missing:
- `knowledge/`, `knowledge/raw/`, `knowledge/wiki/` (each with `.gitkeep`)
- `knowledge/wiki/index.md` — heading `# Knowledge Base Index`, empty body
- `knowledge/wiki/log.md` — heading `# Wiki Log`, empty body

If Query or Lint cannot find the wiki, tell the user "Run an ingest first to initialize the wiki." Do not auto-create.

## Default topic taxonomy

For happysquad work, default topics under `knowledge/wiki/` are:

| Topic         | Contains                                                                    |
|---------------|-----------------------------------------------------------------------------|
| `subsystems`  | Knowledge about specific subsystems/modules (auth, billing, exports, etc.)  |
| `patterns`    | Recurring technical patterns (caching, rate-limiting, error handling, …)    |
| `decisions`   | ADR-style records of design choices and their tradeoffs                     |
| `lessons`     | Rules learned from BLOCKED reports and repeated reviewer issues             |
| `runbook`     | Operational procedures (deploy, rollback, debug, oncall playbooks)          |

Create new top-level topics sparingly. The taxonomy is meant to stay narrow so the index stays readable.

## Ingest

Fetch a source into `knowledge/raw/`, then compile it into `knowledge/wiki/`. Always both steps.

### Happysquad artifact mode

When the `<source>` argument is a path under `.happysquad/runs/<run-id>/` or `.happysquad/brainstorms/<session-id>/`, the skill recognizes the file type and extracts structure automatically:

| Source file                  | Default raw topic    | Suggested wiki destination(s)                          |
|------------------------------|----------------------|--------------------------------------------------------|
| `design.md`                  | `designs`            | `subsystems/<inferred>.md` or `decisions/<slug>.md`    |
| `implementation.md`          | `implementations`    | merge into the subsystem article it modified           |
| `test-report.md`             | `test-reports`       | `subsystems/<inferred>.md` (test-strategy section)     |
| `review.md`                  | `reviews`            | `lessons/<rule-name>.md` if it flagged recurring issues |
| `BLOCKED.md`                 | `blockers`           | `lessons/<slug>.md` (a BLOCKED that wasn't captured as a lesson is a wasted loop) |
| `consensus.md`               | `brainstorms`        | `decisions/<slug>.md` + linked `subsystems/*.md`       |
| `signoffs.md`                | `brainstorms`        | merge into the same decision article                   |

For each ingested artifact:
1. Copy verbatim into `knowledge/raw/<topic>/YYYY-MM-DD-<run-or-session-id>-<file>.md`. Preserve content. Add the metadata header from `references/raw-template.md`.
2. Determine which wiki article(s) the content updates or creates.
3. Compile / update. Refresh `updated` dates. Cascade as below.

### External-source mode

When the source is a URL, a path outside `.happysquad/`, or pasted content:
1. Fetch via available tools. If unreachable, ask the user to paste it.
2. Pick or create a topic directory under `knowledge/raw/`.
3. Save as `knowledge/raw/<topic>/YYYY-MM-DD-<slug>.md` with the metadata header.
4. Compile / update.

See `references/raw-template.md` for the exact raw-file format.

### Compile

Determine where the new content belongs:

- **Same core thesis as an existing article** → Merge into it. Add the new source to Sources / Raw. Update affected sections.
- **New concept** → Create a new article in the most relevant topic directory. Name the file after the concept, not the raw file.
- **Spans multiple topics** → Place in the primary one; add See Also cross-links to the others.

These are not mutually exclusive. A single happysquad design may merge into `subsystems/auth.md` *and* create a fresh `decisions/api-key-prefix-format.md`.

Conflict handling — if the new source contradicts existing content, annotate the disagreement with source attribution. Don't silently overwrite. The squad learns from disagreement, not papered-over consensus.

See `references/article-template.md` for the wiki article format.

### Cascade updates

After updating the primary article:
1. Scan articles in the same topic directory for content affected by the new source.
2. Scan `knowledge/wiki/index.md` for related concepts in other topics.
3. Update every materially affected article. Refresh each one's `updated` date.

Archive pages are **never** cascade-updated (point-in-time snapshots).

### Post-ingest

- Update `knowledge/wiki/index.md` per `references/index-template.md`.
- Append to `knowledge/wiki/log.md`:

```
## [YYYY-MM-DD] ingest | <primary article title>
- Updated: <cascade-updated article>
- Updated: <another>
```

Omit `- Updated:` lines when no cascade updates occur.

## Query

Search the wiki and answer questions. Triggers: "what do we know about X", "summarize Y", "compare A and B", "have we tried X before", "what's our pattern for Z".

### Steps

1. Read `knowledge/wiki/index.md` to locate relevant articles.
2. Read those articles and synthesize an answer.
3. Prefer wiki content over training knowledge. Cite sources with markdown links: `[Article Title](knowledge/wiki/topic/article.md)` — project-root-relative paths for in-conversation citations; within `knowledge/wiki/` files, use paths relative to the current file.
4. Output the answer in the conversation. Do NOT write files unless the user asks to archive.

### Archive

When the user asks to archive an answer:
1. Write a new wiki page following `references/archive-template.md`. Convert in-conversation citation paths (project-root-relative) to file-relative paths for the archive file.
   - Sources: links to the cited wiki articles.
   - No Raw field (archive content derives from articles, not raw sources).
   - File name reflects the query topic.
   - Place in the most relevant topic directory.
2. Always create a new page. Never merge into existing articles.
3. Update `index.md`. Prefix the summary with `[Archived]`.
4. Append to `log.md`:

```
## [YYYY-MM-DD] query | Archived: <page title>
```

## Lint

Two categories.

### Deterministic checks (auto-fix)

**Index consistency** — compare `index.md` against actual files in `wiki/`:
- File exists but missing from index → add entry with `(no summary)` placeholder.
- Index entry points to nonexistent file → mark as `[MISSING]`. Don't delete.

**Internal links** — for every markdown link in `wiki/` article files (body + Sources frontmatter), excluding Raw field links and excluding `index.md`/`log.md`:
- Target missing → search `wiki/` for a file with the same name elsewhere.
  - Exactly one match → fix the path.
  - Zero or multiple → report.

**Raw references** — every Raw-field link must resolve to a file under `raw/`:
- Target missing → same search-and-fix as internal links.

**See Also** — within each topic:
- Add obviously missing cross-references between related articles.
- Remove links to deleted files.

### Heuristic checks (report only)

Use judgment, do not auto-fix:
- Factual contradictions across articles.
- Outdated claims superseded by newer sources.
- Missing conflict annotations.
- Orphan pages with no inbound links.
- Missing cross-topic references.
- Concepts mentioned frequently across articles but lacking a dedicated page.
- Archive pages whose cited articles have been substantially updated since archival.

### Post-lint

Append to `log.md`:

```
## [YYYY-MM-DD] lint | <N> issues found, <M> auto-fixed
```

## Conventions

- Standard markdown only. **Never** use `[[wikilink]]` shorthand — must work in any markdown renderer.
- `wiki/` supports **one** level of topic subdirectories. No deeper nesting.
- Today's date for log entries, Collected dates, Archived dates. `updated` reflects when an article's *knowledge content* materially changed — not cosmetic edits.
- Inside `wiki/` files, all links use paths relative to the current file. In conversation output, use project-root-relative paths.
- Ingest updates `index.md` + `log.md`. Archive updates `index.md` + `log.md`. Lint updates `log.md` (and `index.md` only when auto-fixing entries). Plain Query writes nothing.
- All frontmatter uses standard YAML with semicolon-separated lists for `sources` and `raw` fields.

## Compounding with happysquad

This is the killer feature: every time the squad finishes work, the wiki gets a little smarter.

After a successful `/happysquad-loop`:
- Architecter's `design.md` → goes into `subsystems/<name>.md` (or merges into an existing one)
- Reviewer's `review.md` → flags recurring issue patterns into `lessons/<rule>.md`
- If the loop hit BLOCKED → `BLOCKED.md` → `lessons/<slug>.md` (mandatory — every BLOCKED that isn't a lesson is a future wasted loop)

After a successful `/brainstorm`:
- `consensus.md` → `decisions/<slug>.md` (this is the squad's ADR)
- Dissenting `signoffs.md` entries become the "Alternatives Considered" section of the decision

The orchestrator does not auto-write any of this. It surfaces the offer with a one-line prompt and the user accepts or declines. Auto-write would silently couple `.happysquad/` working files to the committed `knowledge/` artifact — too easy to pollute the wiki.

## Token discipline

- The wiki's value is read-side, not write-side. Spend tokens carefully on synthesis quality, not on padding articles.
- Lead paragraphs are dense — the index pulls them as one-line summaries.
- Cascade updates touch at most 3-5 articles. If a single ingest seems to ripple through 10+ articles, the taxonomy is wrong; tell the user.
- Query reads the index first, then only the articles it cites. Don't grep the whole wiki.

## What this is NOT

- Not a replacement for `.happysquad/` working files. Those stay per-run.
- Not a deploy / publish channel. To push outward (Confluence, Notion, internal docs portal), the user runs their own sync; this skill stops at `knowledge/`.
- Not version-controlled history. The wiki is the *current best understanding* — historical evolution lives in git on the `knowledge/` directory itself.
- Not a database. It's plain markdown. Resist the temptation to encode structured data — that's what code is for.
