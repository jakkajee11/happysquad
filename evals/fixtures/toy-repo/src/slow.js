// Slow-gate helper: the first `npm test` run *under the hs gate* (HS_GATE=1) in a given
// checkout sleeps SLOW_SECS (default 150) so the test gate exceeds the Bash tool's 120s
// comfort zone once. Agents' own runs and red-green worktree runs are instant.
// A flag file in the OS temp dir keyed by cwd makes later gate runs instant.
import { existsSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";

export function slowOnce() {
  const key = createHash("sha1").update(process.cwd()).digest("hex").slice(0, 12);
  const flag = join(tmpdir(), `hs-toy-slow-${key}`);
  if (process.env.HS_GATE !== "1" || process.env.HS_TOY_FAST === "1" || existsSync(flag)) return 0;
  const secs = Number(process.env.SLOW_SECS || 150);
  const end = Date.now() + secs * 1000;
  while (Date.now() < end) {
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 1000);
  }
  writeFileSync(flag, String(Date.now()));
  return secs;
}
