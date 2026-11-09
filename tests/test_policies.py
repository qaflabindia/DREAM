"""Tests for the optional corroboration and dominance promotion policies."""
import unittest

from dreamlab import DreamEngine, Event


def add(db, subj, val, src, trust="validated"):
    db.ingest(Event("t", subj, "value", val, src, trust=trust, consent=True))


def top(db, subj):
    r = db.recall("t", f"{subj} value", limit=1)
    return (r[0]["text"].split(": ", 1)[1], r[0]["status"]) if r and r[0]["subject"] == subj else (None, None)


class PolicyTests(unittest.TestCase):
    def test_default_single_validated_source_is_verified(self):
        with DreamEngine(":memory:") as db:
            add(db, "x", "a", "s1"); db.dream("t")
            self.assertEqual(("a", "verified"), top(db, "x"))

    def test_corroboration_downgrades_single_source(self):
        with DreamEngine(":memory:", min_verified_sources=2) as db:
            add(db, "x", "a", "s1"); db.dream("t")
            self.assertEqual(("a", "reported"), top(db, "x"))
            add(db, "x", "a", "s2"); db.dream("t")
            self.assertEqual(("a", "verified"), top(db, "x"))

    def test_corroboration_counts_distinct_sources_only(self):
        with DreamEngine(":memory:", min_verified_sources=2) as db:
            add(db, "x", "a", "s1"); add(db, "x", "a", "s1"); db.dream("t")
            self.assertEqual("reported", top(db, "x")[1])

    def test_default_policy_lets_observed_contradiction_withhold_fact(self):
        with DreamEngine(":memory:") as db:
            for s in ("s1", "s2", "s3"):
                add(db, "x", "a", s)
            add(db, "x", "b", "anon", trust="observed"); db.dream("t")
            self.assertEqual((None, None), top(db, "x"))

    def test_dominance_keeps_stronger_value_and_records_disagreement(self):
        with DreamEngine(":memory:", contest_policy="dominance") as db:
            for s in ("s1", "s2"):
                add(db, "x", "a", s)
            add(db, "x", "b", "anon", trust="observed"); db.dream("t")
            self.assertEqual(("a", "verified"), top(db, "x"))
            meta = db.recall("t", "x value", limit=1)[0]["meta"]
            self.assertIn("b", meta["untrusted_alternatives"])

    def test_dominance_ties_remain_contested(self):
        with DreamEngine(":memory:", contest_policy="dominance") as db:
            add(db, "x", "a", "s1"); add(db, "x", "b", "s2"); db.dream("t")
            self.assertEqual((None, None), top(db, "x"))

    def test_invalid_policy_arguments_rejected(self):
        with self.assertRaises(ValueError):
            DreamEngine(":memory:", min_verified_sources=0)
        with self.assertRaises(ValueError):
            DreamEngine(":memory:", contest_policy="majority")


if __name__ == "__main__":
    unittest.main()
