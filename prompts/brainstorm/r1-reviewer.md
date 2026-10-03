# Reviewer — Round 1

> Brainstorm round: this is a discussion, not a dev-loop phase. Ignore the parts of your role file about owned files, ownership gaps, build/test commands, red→green proof, `out.json` and `validate`. The only output is the markdown file named below, ending with the marker line.

When dispatched inside a `/brainstorm` session, you do NOT review code (there is none yet). You write perspective documents in `.happysquad/brainstorms/<session-id>/`.

Write `round1-reviewer.md`: risk lens. Cover: what's the production failure mode of getting this wrong (security incident, data loss, perf regression, compliance miss), what's the blast radius if it fails, what dependencies could fail externally, what regression surface the change creates in adjacent code, what could not-be-undone after ship. ~400 words.

REVIEWER_R1_READY: <path>

Then stop: end your turn with the marker line as your last line. Do not wait for anything, do not schedule a follow-up, do not journal to PROGRESS.md.
