# hs-toy

Zero-dependency ESM Node project used as the happysquad eval fixture.

- Build: `npm run build`
- Test: `npm test` (writes `coverage/lcov.info`). One file: `npm test -- test/<name>.test.js`.
- The engine's test gate can take ~150s on its first run by design; always pass a 600000 ms timeout to the Bash tool when waiting on it.
- Tests live in `test/*.test.js`, use `node:test` + `node:assert/strict`.
- Source lives in `src/`. Keep functions small and pure.
