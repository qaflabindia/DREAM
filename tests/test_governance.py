"""Reproducible, scoped fault tests. No external network or credentials."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from dreamlab import DreamEngine, Event
from dreamlab.engine import IntegrityError

class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.d = DreamEngine(Path(self.temp.name)/"evidence.sqlite")

    def tearDown(self):
        self.d.close(); self.temp.cleanup()

    def add(self, subject, predicate, value, source="source", **kw):
        return self.d.ingest(Event("tenant", subject, predicate, value, source, consent=True, **kw))

    def test_untrusted_contradiction_not_promoted_or_authoritative_veto(self):
        self.add("account", "state", "solvent", trust="validated")
        self.d.dream("tenant")
        self.add("account", "state", "insolvent", "anonymous", trust="untrusted")
        # The original validated item remains available until adjudication.
        self.assertEqual(1, len(self.d.recall("tenant", "account state")))
        self.d.dream("tenant")
        mem = self.d.recall("tenant", "account state")[0]
        self.assertEqual("verified", mem["status"])
        self.assertEqual(["insolvent"], mem["meta"]["untrusted_alternatives"])

    def test_untrusted_expiry_does_not_revoke_validated_fact(self):
        self.add("company", "state", "solvent", "verified-record", trust="validated")
        self.add("company", "state", "insolvent", "untrusted-record", trust="untrusted",
                 expires_at="2027-01-01T00:00:00+00:00")
        self.d.dream("tenant")
        with patch("dreamlab.engine.now_utc", return_value="2028-01-01T00:00:00+00:00"):
            self.assertEqual(1, len(self.d.recall("tenant", "company state")))

    def test_validated_conflict_blocks_promotion(self):
        self.add("account", "state", "open", "one", trust="validated")
        self.add("account", "state", "closed", "two", trust="validated")
        self.d.dream("tenant")
        self.assertEqual([], self.d.recall("tenant", "account state"))

    def test_tampered_value_is_rejected_at_dream(self):
        eid = self.add("plan", "status", "approved", trust="validated")
        self.d.db.execute("UPDATE events SET value='rejected' WHERE id=?", (eid,))
        with self.assertRaises(IntegrityError):
            self.d.dream("tenant")

    def test_tampered_source_class_is_rejected(self):
        eid = self.add("plan", "status", "pending", trust="observed")
        self.d.db.execute("UPDATE events SET trust='validated' WHERE id=?", (eid,))
        with self.assertRaises(IntegrityError):
            self.d.dream("tenant")

    def test_tampered_importance_is_rejected(self):
        eid = self.add("plan", "status", "active", trust="validated")
        self.d.db.execute("UPDATE events SET importance=0.9 WHERE id=?", (eid,))
        with self.assertRaises(IntegrityError):
            self.d.dream("tenant")

    def test_tampered_approved_fact_is_not_retrieved(self):
        eid = self.add("plan", "status", "approved", trust="validated")
        self.d.dream("tenant")
        self.d.db.execute("UPDATE events SET value='rejected' WHERE id=?", (eid,))
        with self.assertRaises(IntegrityError):
            self.d.recall("tenant", "plan status")

    def test_expired_procedure_revoked_at_read_and_next_dream(self):
        self.add("decimal_sum", "attempt", "failed", kind="outcome", trust="observed",
                 expires_at="2027-01-01T00:00:00+00:00", importance=1,
                 payload={"scenario":"decimal_sum", "action":"binary_float"})
        self.d.dream("tenant")
        self.assertEqual(1, len(self.d.recall("tenant", "decimal_sum action_policy")))
        with patch("dreamlab.engine.now_utc", return_value="2028-01-01T00:00:00+00:00"):
            self.assertEqual([], self.d.recall("tenant", "decimal_sum action_policy"))
            self.d.dream("tenant")
        statuses = [x["status"] for x in self.d.memories("tenant", include_inactive=True) if x["memory_type"] == "procedure"]
        self.assertEqual(["expired"], statuses)

    def test_inspection_endpoint_respects_clearance(self):
        self.add("payroll", "amount", "100", trust="validated", sensitivity="restricted")
        self.d.dream("tenant")
        self.assertEqual([], self.d.memories("tenant"))
        self.assertEqual([], self.d.memories("tenant", include_inactive=True))
        self.assertEqual(1, len(self.d.memories("tenant", clearance="restricted")))

    def test_untrusted_priority_flood_cannot_starve_validated(self):
        self.add("critical", "policy", "must-check", "official", trust="validated", importance=.1)
        for i in range(40):
            self.add(f"junk{i}", "event", "noise", f"anonymous-{i}",
                     trust="untrusted", kind="correction", importance=1)
        self.d.dream("tenant", max_events=16, max_keys=8)
        mem = self.d.recall("tenant", "critical policy")
        self.assertEqual(1, len(mem))

    def test_benign_expiry_is_not_an_integrity_failure(self):
        self.add("release", "state", "ready", trust="validated", expires_at="2027-01-01T00:00:00+00:00")
        self.d.dream("tenant")
        with patch("dreamlab.engine.now_utc", return_value="2028-01-01T00:00:00+00:00"):
            self.assertEqual([], self.d.recall("tenant", "release state"))

if __name__ == '__main__': unittest.main()
