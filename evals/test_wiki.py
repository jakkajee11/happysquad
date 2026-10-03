"""Unit tests for hs.wiki (deterministic dev-wiki Lint half). No git, no model.

Run: python3 -m unittest discover -s evals -p 'test_wiki.py' -v
"""
import os
import sys
import tempfile
import unittest
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from hs import wiki  # noqa: E402


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class WikiLintFixture(unittest.TestCase):
    """2 topics, 3 wiki articles + 2 decoys, 1 raw file; one of every lint-able defect:
    - index missing an article (beta.md) and listing a deleted one (ghost.md)
    - a broken internal link whose basename is unique elsewhere -> fixable (alpha -> moved-article.md)
    - a broken internal link whose basename is ambiguous -> reported (alpha -> dup.md, x2)
    - a broken raw: link whose basename is unique elsewhere -> fixable
    - a See Also bullet pointing at nothing -> pruned
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.wiki = os.path.join(self.root, "knowledge", "wiki")
        self.raw = os.path.join(self.root, "knowledge", "raw")

        _write(os.path.join(self.wiki, "index.md"), (
            "# Knowledge Base Index\n\n"
            "## Subsystems\n\n"
            "- [Alpha](subsystems/alpha.md) — the alpha subsystem · Updated 2026-05-20\n"
            "- [Ghost](subsystems/ghost.md) — a deleted article · Updated 2026-05-01\n"
        ))
        _write(os.path.join(self.wiki, "log.md"), "# Wiki Log\n")

        _write(os.path.join(self.wiki, "subsystems", "alpha.md"), (
            "---\n"
            "title: Alpha\n"
            "topic: subsystems\n"
            "raw: [src](../../raw/subsystems/auth-notes-old.md)\n"
            "updated: 2026-05-20\n"
            "---\n\n"
            "# Alpha\n\n"
            "Lead paragraph for Alpha.\n\n"
            "See [Renamed](../subsystems/moved-article.md) for context.\n\n"
            "See [Dup](../subsystems/dup.md) too.\n\n"
            "## See Also\n\n"
            "- [Gone](../subsystems/nowhere.md) — stale link\n"
        ))

        _write(os.path.join(self.wiki, "subsystems", "beta.md"), (
            "---\n"
            "title: Beta\n"
            "topic: subsystems\n"
            "updated: 2026-05-20\n"
            "---\n\n"
            "# Beta\n\n"
            "Lead paragraph for Beta, not yet in the index.\n"
        ))

        # the real file alpha's broken "Renamed" link should resolve to (same basename, different topic)
        _write(os.path.join(self.wiki, "patterns", "moved-article.md"), (
            "---\ntitle: Moved Article\ntopic: patterns\nupdated: 2026-05-20\n---\n\n"
            "# Moved Article\n\nIt moved.\n"
        ))

        # two files sharing basename "dup.md" -> ambiguous
        _write(os.path.join(self.wiki, "patterns", "dup.md"),
               "---\ntitle: Dup One\ntopic: patterns\nupdated: 2026-05-20\n---\n\n# Dup One\n\nx\n")
        _write(os.path.join(self.wiki, "lessons", "dup.md"),
               "---\ntitle: Dup Two\ntopic: lessons\nupdated: 2026-05-20\n---\n\n# Dup Two\n\ny\n")

        # the real raw file alpha's broken raw: link should resolve to (same basename, different topic dir)
        _write(os.path.join(self.raw, "misc", "auth-notes-old.md"), "---\ntitle: Auth notes\n---\n\n# Auth notes\n")

    def tearDown(self):
        self.tmp.cleanup()

    def _snapshot(self):
        snap = {}
        for dirpath, _d, files in os.walk(self.root):
            for fn in files:
                p = os.path.join(dirpath, fn)
                snap[p] = _read(p)
        return snap


class TestDryRun(WikiLintFixture):
    def test_dry_run_changes_nothing_but_reports_counts(self):
        before = self._snapshot()

        res = wiki.lint(self.root, dry_run=True)

        self.assertTrue(res["ok"])
        self.assertTrue(res["dry_run"])
        # index-add fires for every *.md under a topic dir not yet in the index — beta.md (the one we
        # care about) plus the 3 decoy files (moved-article.md, two dup.md) planted as fix targets.
        kind_counts = Counter(f["kind"] for f in res["fixes"])
        self.assertEqual(kind_counts, Counter(
            {"index-add": 4, "index-missing": 1, "link-fix": 1, "raw-fix": 1, "see-also-prune": 1}))
        report_kinds = [r["kind"] for r in res["reports"]]
        self.assertEqual(report_kinds, ["link-ambiguous"])
        self.assertEqual(res["fixed"], 8)
        self.assertEqual(res["issues"], 9)

        self.assertEqual(before, self._snapshot())


class TestRealRun(WikiLintFixture):
    def test_fixes_applied_and_log_appended(self):
        res = wiki.lint(self.root)

        self.assertTrue(res["ok"])
        self.assertFalse(res["dry_run"])
        self.assertEqual(res["fixed"], 8)
        self.assertEqual(len(res["reports"]), 1)

        index = _read(os.path.join(self.wiki, "index.md"))
        self.assertIn("[MISSING] a deleted article", index)
        self.assertIn("[Beta](subsystems/beta.md)", index)

        alpha = _read(os.path.join(self.wiki, "subsystems", "alpha.md"))
        self.assertIn("(../patterns/moved-article.md)", alpha)
        self.assertIn("(../subsystems/dup.md)", alpha)  # ambiguous -> left as-is, reported not fixed
        self.assertNotIn("Gone", alpha)  # see-also-prune removed the dead bullet
        self.assertIn("raw: [src](../../raw/misc/auth-notes-old.md)\n", alpha)

        log = _read(os.path.join(self.wiki, "log.md"))
        self.assertEqual(log.count("## ["), 1)
        self.assertIn("lint | 9 issues found, 8 auto-fixed", log)

    def test_idempotent_second_run(self):
        first = wiki.lint(self.root)
        second = wiki.lint(self.root)

        self.assertEqual(second["fixed"], 0)
        self.assertEqual(second["issues"], len(second["reports"]))
        self.assertEqual(second["reports"], first["reports"])
        self.assertTrue(second["reports"])  # the ambiguous Dup link is never auto-fixable

        log = _read(os.path.join(self.wiki, "log.md"))
        self.assertEqual(log.count("## ["), 2)


class TestNoWiki(unittest.TestCase):
    def test_missing_wiki_is_an_error(self):
        with tempfile.TemporaryDirectory() as root:
            res = wiki.lint(root)
            self.assertFalse(res["ok"])
            self.assertIn("error", res)


if __name__ == "__main__":
    unittest.main()
