# PERF axis checklist

Scope: performance only. Use the design's stated scale; do not invent one. Point at the mechanism (table scan, round trip per iteration, lock held across I/O).

1. **N+1** — a query inside a loop; missing eager/batch load.
2. **Unbounded work** — runtime grows with user input or data size with no cap or pagination.
3. **Missing index** — new predicate with no supporting index (check migrations/ORM mappings).
4. **Sync I/O on hot paths** — blocking file/network calls in request handlers or event loops.
5. **Algorithmic regression** — O(n) → O(n²), redundant sorts, scans where lookups exist.
6. **Retention / leaks** — ever-growing collections, listeners never removed, large buffers held.
7. **Locks** — broad locks, deadlock risk, blocking await chains.
8. **Caching** — over-broad keys, stampede risk, missing invalidation.
9. **Serialization** — large graphs on hot paths, repeated parse/reflection.
10. **External calls** — no timeout, no backoff, inside loops.
11. **Migrations** — table locks during deploy, unbatched backfills.

Severity: `blocker` = measurable degradation under the design's stated load; `major` = real but off the hot path; `minor` = future-proofing. Over-reporting costs credibility; a 5-item loop once per request is not a finding.
