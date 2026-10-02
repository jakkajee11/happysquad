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
    "blocked-cap": 10,
    "no-new-tests": 4,
    "tests-fail-with-findings": 7,
}


@unittest.skipUnless(shutil.which("node") and shutil.which("git"), "requires node and git")
class TestE2E(unittest.TestCase):
    pass


def _make_test(name, expect_dispatches):
    def test(self):
        proc = subprocess.run(["bash", RUN_FAKE, name], capture_output=True, text=True, timeout=240)
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
