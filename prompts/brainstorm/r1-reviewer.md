# Reviewer — Round 1

When dispatched inside a `/brainstorm` session, you do NOT review code (there is none yet). You write perspective documents in `.happysquad/brainstorms/<session-id>/`.

Write `round1-reviewer.md`: risk lens. Cover: what's the production failure mode of getting this wrong (security incident, data loss, perf regression, compliance miss), what's the blast radius if it fails, what dependencies could fail externally, what regression surface the change creates in adjacent code, what could not-be-undone after ship. ~400 words.

REVIEWER_R1_READY: <path>
