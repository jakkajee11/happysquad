"""$0 e2e tests: drive `evals/run_fake.sh <scenario>` and check it reaches the expected terminal state.

Each scenario's expected status/cause is also declared in evals/scenarios/<name>.json under
"_expect"/"_expect_cause" (read by run_fake.sh itself); the dispatch counts here were obtained by
running each scenario once and are asserted so a future engine change that alters the dispatch
count is caught.
"""
import os
import re
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RUN_FAKE = os.path.join(HERE, "run_fake.sh")

# name -> (expected dispatch count or None if not asserted)
SCENARIOS = {
    "pass-first": 4,
    "validation-retry": 5,
    "validation-blocked": 3,
    "gate-build-fail": 3,
    "review-fail-then-pass": 7,
    "blocked-cap": 11,  # P1a: converge() zero-progress rule adds one more full round (spec §8.3) before BLOCKED
    "no-new-tests": 6,  # v1.0 G-COV now enforces per-file coverage (0.16 didn't); costs one extra TEST+REVIEW round
    "tests-fail-with-findings": 7,
    # P1a additions (spec §4-§8): inner-fix loop, convergence, parallel waves, conflict gate,
    # risk-split specialists, lite.
    "fail-inner-fix": 6,
    "inner-cap-fallback": 9,  # inner_cap=2 = two fix passes (p0, p1), then a full round
    "repeat-escalate": 11,
    "parallel-2ws": 6,
    "parallel-deps": 6,  # util depends_on calc: IMPLEMENT and TEST each come as two sequential single dispatches
    "ownership-gap": 6,  # implementer stops on a gap -> architect re-run in-iteration -> fresh IMPLEMENT-i1-r1 consumed
    "ownership-violation": 9,
    "risk-sec": 5,
    "risk-sec-blocks": 9,
    "lite-forced": 4,
}

# extra environment for a scenario's run_fake.sh invocation (e.g. RUN_FLAGS=--lite)
SCENARIO_ENV = {
    "lite-forced": {"RUN_FLAGS": "--lite"},
}


@unittest.skipUnless(shutil.which("node") and shutil.which("git"), "requires node and git")
class TestE2E(unittest.TestCase):
    pass


def _make_test(name, expect_dispatches):
    def test(self):
        env = dict(os.environ, **SCENARIO_ENV.get(name, {}))
        proc = subprocess.run(["bash", RUN_FAKE, name], capture_output=True, text=True, timeout=240, env=env)
        lines = proc.stdout.strip().splitlines()
        tail = "\n".join(lines[-3:])
        self.assertEqual(proc.returncode, 0, "scenario %s failed:\n%s\n%s" % (name, tail, proc.stderr[-2000:]))
        m = re.search(r"DONE status=\S+ dispatches=(\d+)", proc.stdout)
        self.assertIsNotNone(m, "no DONE line for %s:\n%s" % (name, tail))
        if expect_dispatches is not None:
            self.assertEqual(int(m.group(1)), expect_dispatches,
                             "%s: expected %d dispatches, got %s" % (name, expect_dispatches, m.group(1)))
    return test


for _name, _n in SCENARIOS.items():
    setattr(TestE2E, "test_" + _name.replace("-", "_"), _make_test(_name, _n))


if __name__ == "__main__":
    unittest.main()
