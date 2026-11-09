"""An auditable, offline dream cycle with strict evidence and privacy boundaries.

Research prototype: lexical search, finite registered sandbox; no neural model.
SQLite is local and UNENCRYPTED. Never ingest secrets or personal records.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .llm import HypothesisProposer
from .scenarios import evaluate_counterfactual

TRUST = {"untrusted", "observed", "self_report", "validated"}
SENSITIVITY = {"public": 0, "private": 1, "restricted": 2}
KINDS = {"observation", "feedback", "outcome", "correction"}
STOPWORDS = {"a", "an", "the", "is", "of", "for", "to", "in", "as", "with", "and", "or", "on", "what", "how", "do", "i"}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower())) - STOPWORDS


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# Integrity checks detect accidental/unrecorded row mutations. An attacker with
# write access to the database can recompute an unkeyed digest: use external
# authentication/append-only infrastructure before any multi-user deployment.
EVENT_DIGEST_FIELDS = ("id", "tenant", "subject", "predicate", "value", "source_id",
                       "kind", "trust", "importance", "sensitivity", "payload",
                       "created_at", "expires_at")


def event_digest(values: dict[str, Any]) -> str:
    canonical = json.dumps({name: values[name] for name in EVENT_DIGEST_FIELDS},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IntegrityError(ValueError):
    """Stored evidence no longer matches its recorded content digest."""


@dataclass(frozen=True)
class Event:
    tenant: str
    subject: str
    predicate: str
    value: str
    source_id: str
    kind: str = "observation"
    trust: str = "observed"
    importance: float = 0.5
    sensitivity: str = "public"
    consent: bool = False
    payload: dict[str, Any] = field(default_factory=dict)
    expires_at: str | None = None


class DreamEngine:
    def __init__(self, db_path: str | Path, *, min_verified_sources: int = 1,
                 contest_policy: str = "any"):
        """min_verified_sources: distinct validated source_ids that must agree
        before a fact is labelled 'verified'. With fewer, a validated value is
        served as 'reported'. Source identifiers are caller-supplied and are
        not authenticated, so this raises attack cost but is not proof."""
        if min_verified_sources < 1:
            raise ValueError("min_verified_sources must be >= 1")
        if contest_policy not in {"any", "dominance"}:
            raise ValueError("contest_policy must be 'any' or 'dominance'")
        self.min_verified_sources = min_verified_sources
        # 'any': any non-untrusted disagreement contests the key (withheld).
        # 'dominance': a value whose (best trust rank, distinct sources at that
        # rank) strictly exceeds every alternative stays servable; the
        # disagreement is kept in metadata. Ties are still contested.
        self.contest_policy = contest_policy
        self.db_path = str(db_path)
        self.db = sqlite3.connect(self.db_path, timeout=20, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self._init_db()

    def __enter__(self) -> "DreamEngine":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.db.close()

    def _init_db(self) -> None:
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
              id TEXT PRIMARY KEY, tenant TEXT NOT NULL, subject TEXT NOT NULL,
              predicate TEXT NOT NULL, value TEXT NOT NULL, source_id TEXT NOT NULL,
              kind TEXT NOT NULL, trust TEXT NOT NULL, importance REAL NOT NULL,
              sensitivity TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
              expires_at TEXT, digest TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_tenant_key ON events(tenant, subject, predicate);
            CREATE TABLE IF NOT EXISTS memories (
              id TEXT PRIMARY KEY, tenant TEXT NOT NULL, subject TEXT NOT NULL,
              predicate TEXT NOT NULL, text TEXT NOT NULL, memory_type TEXT NOT NULL,
              status TEXT NOT NULL, confidence REAL NOT NULL, importance REAL NOT NULL,
              sensitivity TEXT NOT NULL, evidence_json TEXT NOT NULL, meta_json TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(tenant, subject, predicate, memory_type)
            );
            CREATE INDEX IF NOT EXISTS idx_memories_tenant ON memories(tenant, status);
            CREATE TABLE IF NOT EXISTS audit (
              id TEXT PRIMARY KEY, tenant TEXT NOT NULL, run_id TEXT NOT NULL,
              action TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS hypotheses (
              id TEXT PRIMARY KEY, tenant TEXT NOT NULL, dream_run_id TEXT NOT NULL,
              claim TEXT NOT NULL, rationale TEXT NOT NULL, test_plan TEXT NOT NULL,
              evidence_json TEXT NOT NULL, model_name TEXT NOT NULL,
              status TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_hypotheses_tenant ON hypotheses(tenant);
            CREATE TABLE IF NOT EXISTS dream_runs (
              id TEXT PRIMARY KEY, tenant TEXT NOT NULL, started_at TEXT NOT NULL,
              replayed INTEGER NOT NULL, consolidated INTEGER NOT NULL,
              contested INTEGER NOT NULL, counterfactuals INTEGER NOT NULL
            );
        """)

    def _audit(self, tenant: str, run_id: str, action: str, details: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO audit VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4()), tenant, run_id, action, json.dumps(details, sort_keys=True), now_utc()),
        )

    def ingest(self, event: Event) -> str:
        if not event.consent:
            raise ValueError("Explicit permission to store this event is required")
        if not all([event.tenant.strip(), event.subject.strip(), event.predicate.strip(), event.source_id.strip()]):
            raise ValueError("tenant, subject, predicate, source_id must be nonempty")
        if event.trust not in TRUST or event.kind not in KINDS or event.sensitivity not in SENSITIVITY:
            raise ValueError("Unknown evidence classification")
        if not math.isfinite(event.importance) or not (0 <= event.importance <= 1):
            raise ValueError("importance must be a finite number in [0, 1]")
        if len(event.value) > 16000 or len(json.dumps(event.payload)) > 16000:
            raise ValueError("Event exceeds local prototype limits")
        expires_at = None
        if event.expires_at:
            dt = datetime.fromisoformat(event.expires_at)
            if dt.tzinfo is None:
                raise ValueError("Expiry timestamp must include a timezone offset")
            expires_at = dt.astimezone(timezone.utc).isoformat()
        event_id = str(uuid.uuid4())
        payload = json.dumps(event.payload, sort_keys=True)
        created = now_utc()
        event_values = {
            "id": event_id, "tenant": event.tenant, "subject": event.subject,
            "predicate": event.predicate, "value": event.value,
            "source_id": event.source_id, "kind": event.kind, "trust": event.trust,
            "importance": float(event.importance), "sensitivity": event.sensitivity,
            "payload": payload, "created_at": created, "expires_at": expires_at,
        }
        digest = event_digest(event_values)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute("""INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event_id, event.tenant, event.subject, event.predicate, event.value,
                 event.source_id, event.kind, event.trust, event.importance,
                 event.sensitivity, payload, created, expires_at, digest))
            # New evidence invalidates an old consolidated fact immediately.
            # Never serve it again before the next conflict-aware dream cycle.
            # A low-integrity report is indexed as a disagreement, but cannot
            # revoke the visibility of previously validated evidence on its own.
            if event.trust != "untrusted":
                self.db.execute("""UPDATE memories SET status='stale'
                    WHERE tenant=? AND subject=? AND predicate=? AND memory_type='fact'""",
                    (event.tenant, event.subject, event.predicate))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return event_id

    @staticmethod
    def _verify_row(r: sqlite3.Row) -> None:
        if event_digest(dict(r)) != r["digest"]:
            raise IntegrityError(f"Evidence integrity mismatch: {r['id']}")

    def _supports_active_memory(self, tenant: str, evidence: list[str]) -> bool:
        # Every supporting record must exist, be tenant-local, be current and be
        # unchanged. Applied to facts AND procedures at every authorized read.
        if not evidence:
            return False
        cutoff = now_utc()
        for eid in evidence:
            r = self.db.execute("SELECT * FROM events WHERE id=? AND tenant=?",
                                (eid, tenant)).fetchone()
            if r is None or (r["expires_at"] is not None and r["expires_at"] <= cutoff):
                return False
            self._verify_row(r)
        return True

    @staticmethod
    def _replay_score(r: sqlite3.Row) -> float:
        # Failure signal + user-defined impact; not confidence or objective correctness.
        failure = 1 if r["kind"] in {"correction", "outcome"} else 0
        trust_weight = {"untrusted": 0.0, "observed": 0.15, "self_report": 0.1, "validated": 0.3}[r["trust"]]
        return (0.6 * r["importance"] + 0.25 * failure + trust_weight)

    def _upsert_memory(self, tenant: str, subject: str, predicate: str, memory_type: str,
                       text: str, status: str, confidence: float, importance: float,
                       sensitivity: str, evidence: list[str], meta: dict[str, Any]) -> None:
        self.db.execute("""
          INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(tenant, subject, predicate, memory_type) DO UPDATE SET
            text=excluded.text, status=excluded.status, confidence=excluded.confidence,
            importance=excluded.importance, sensitivity=excluded.sensitivity,
            evidence_json=excluded.evidence_json, meta_json=excluded.meta_json,
            updated_at=excluded.updated_at
        """, (str(uuid.uuid4()), tenant, subject, predicate, text, memory_type,
              status, confidence, importance, sensitivity,
              json.dumps(evidence), json.dumps(meta, sort_keys=True), now_utc()))

    def dream(self, tenant: str, *, max_events: int = 256, max_keys: int = 64) -> dict[str, Any]:
        """Finite, deterministic replay and promotion. Calls no external tools/models."""
        if not tenant.strip() or not 1 <= max_events <= 10000 or not 1 <= max_keys <= 1000:
            raise ValueError("Invalid tenant or dream limits")
        run_id = str(uuid.uuid4())
        cutoff = now_utc()
        # Transaction prevents concurrent dreams from interleaving memory writes.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            selected = self.db.execute("""SELECT * FROM events WHERE tenant=?
                AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY CASE trust WHEN 'validated' THEN 3 WHEN 'observed' THEN 2
                     WHEN 'self_report' THEN 1 ELSE 0 END DESC,
                     (CASE WHEN trust='untrusted' THEN 0 ELSE
                        0.6 * importance + CASE WHEN kind IN ('correction','outcome')
                        THEN 0.25 ELSE 0 END END) DESC,
                     created_at DESC LIMIT ?""", (tenant, cutoff, max_events)).fetchall()
            for r in selected:
                self._verify_row(r)
            keys = []
            seen = set()
            for r in selected:
                key = (r["subject"], r["predicate"])
                if key not in seen:
                    seen.add(key)
                    keys.append(key)
                if len(keys) >= max_keys:
                    break
            consolidated = contested = counterfactuals = 0
            for subject, predicate in keys:
                # Pull ALL active sibling evidence for each selected key: prevents a
                # limited replay sample from hiding a low-priority contradiction.
                group = self.db.execute("""SELECT * FROM events WHERE tenant=?
                    AND subject=? AND predicate=?
                    AND (expires_at IS NULL OR expires_at > ?)""",
                    (tenant, subject, predicate, cutoff)).fetchall()
                for r in group:
                    self._verify_row(r)
                # Low-integrity alternatives are recorded without allowing an
                # anonymous observation to silence an already validated claim.
                ranked_group = [r for r in group if r["trust"] != "untrusted"]
                active_group = ranked_group if ranked_group else group
                grouped: dict[str, list[sqlite3.Row]] = {}
                for r in active_group:
                    norm = " ".join(r["value"].lower().split())
                    grouped.setdefault(norm, []).append(r)
                low_trust_disagreements = sorted({" ".join(r["value"].lower().split())
                    for r in group if r["trust"] == "untrusted"} - set(grouped))
                max_sensitivity = max(group, key=lambda r: SENSITIVITY[r["sensitivity"]])["sensitivity"]
                # Only the evidence used to authorize the selected conclusion
                # is a hard retrieval dependency. Untrusted alternatives remain
                # separately traceable, without gaining a revocation veto.
                evidence_ids = [r["id"] for r in active_group]
                importance = max(r["importance"] for r in active_group)
                winner = None
                if len(grouped) > 1 and self.contest_policy == "dominance":
                    rank = {"validated": 3, "observed": 2, "self_report": 1, "untrusted": 0}
                    def strength(rows):
                        best = max(rank[r["trust"]] for r in rows)
                        return (best, len({r["source_id"] for r in rows if rank[r["trust"]] == best}))
                    ordered = sorted(grouped, key=lambda v: strength(grouped[v]), reverse=True)
                    if strength(grouped[ordered[0]]) > strength(grouped[ordered[1]]):
                        winner = ordered[0]
                if winner is not None:
                    low_trust_disagreements = sorted(set(low_trust_disagreements) | (set(grouped) - {winner}))
                    ranked_group = [r for r in ranked_group if " ".join(r["value"].lower().split()) == winner]
                    active_group = ranked_group
                    evidence_ids = [r["id"] for r in active_group]
                    grouped = {winner: active_group}
                if len(grouped) > 1:
                    status, confidence, val = "contested", 0.0, " | ".join(sorted(grouped))
                    contested += 1
                elif not ranked_group:
                    val = active_group[0]["value"]
                    status, confidence = "quarantined", 0.0
                else:
                    val = active_group[0]["value"]
                    trusts = {r["trust"] for r in ranked_group}
                    validated_sources = {r["source_id"] for r in ranked_group if r["trust"] == "validated"}
                    if len(validated_sources) >= self.min_verified_sources:
                        status, confidence = "verified", 0.95
                    elif validated_sources or "self_report" in trusts:
                        status, confidence = "reported", 0.65
                    else:
                        status, confidence = "pending", 0.35
                self._upsert_memory(
                    tenant, subject, predicate, "fact", f"{subject} / {predicate}: {val}",
                    status, confidence, importance, max_sensitivity, evidence_ids,
                    {"source_ids": sorted({r["source_id"] for r in group}),
                     "alternative_count": len(grouped),
                     "untrusted_alternatives": low_trust_disagreements,
                     "untrusted_evidence": [r["id"] for r in group if r["trust"] == "untrusted"]}
                )
                consolidated += 1
                self._audit(tenant, run_id, "consolidate", {"key": [subject, predicate], "status": status})
                # Only a registered, safe simulator is allowed to test alternatives.
                for r in group:
                    if r["kind"] != "outcome" or r["trust"] not in {"observed", "validated"}:
                        continue
                    payload = json.loads(r["payload"])
                    if not isinstance(payload, dict):
                        continue
                    scenario, action = payload.get("scenario"), payload.get("action")
                    if not isinstance(scenario, str) or not isinstance(action, str):
                        continue
                    experiment = evaluate_counterfactual(scenario, action)
                    if experiment is None:
                        continue
                    counterfactuals += 1
                    self._audit(tenant, run_id, "counterfactual", {"event_id": r["id"], **experiment})
                    if experiment["improved"]:
                        self._upsert_memory(
                            tenant, scenario, "action_policy", "procedure",
                            experiment["rule"], "sandbox_verified", 0.8,
                            r["importance"], r["sensitivity"], [r["id"]], experiment)
            # Expiration is transitive: revoke facts and derived procedures alike.
            for memory in self.db.execute(
                "SELECT id, evidence_json FROM memories WHERE tenant=? AND status IN "
                "('verified','reported','sandbox_verified','pending')", (tenant,)).fetchall():
                evidence = json.loads(memory["evidence_json"])
                if not self._supports_active_memory(tenant, evidence):
                    self.db.execute("UPDATE memories SET status='expired', updated_at=? WHERE id=?",
                                    (now_utc(), memory["id"]))
            self.db.execute("""INSERT INTO dream_runs VALUES (?,?,?,?,?,?,?)""",
                (run_id, tenant, cutoff, len(selected), consolidated, contested, counterfactuals))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return {"run_id": run_id, "tenant": tenant, "replayed": len(selected),
                "consolidated": consolidated, "contested": contested,
                "counterfactuals": counterfactuals}

    def memories(self, tenant: str, *, include_inactive: bool = False,
                 clearance: str = "public") -> list[dict[str, Any]]:
        if clearance not in SENSITIVITY:
            raise ValueError("Invalid clearance")
        rows = self.db.execute("SELECT * FROM memories WHERE tenant=? ORDER BY updated_at DESC", (tenant,)).fetchall()
        result = []
        for r in rows:
            if SENSITIVITY[r["sensitivity"]] > SENSITIVITY[clearance]:
                continue
            if include_inactive:
                result.append(self._memory_dict(r))
            elif r["status"] in {"verified", "reported", "sandbox_verified"} and \
                    self._supports_active_memory(tenant, json.loads(r["evidence_json"])):
                result.append(self._memory_dict(r))
        return result

    @staticmethod
    def _memory_dict(r: sqlite3.Row) -> dict[str, Any]:
        return {k: r[k] for k in ["id", "tenant", "subject", "predicate", "text", "memory_type",
                                    "status", "confidence", "importance", "sensitivity", "updated_at"]} | {
                  "evidence": json.loads(r["evidence_json"]), "meta": json.loads(r["meta_json"])}

    def recall(self, tenant: str, query: str, *, clearance: str = "public", limit: int = 5,
               max_chars: int = 4000) -> list[dict[str, Any]]:
        if clearance not in SENSITIVITY or not 1 <= limit <= 100 or max_chars < 32:
            raise ValueError("Invalid recall parameters")
        q = tokens(query)
        if not q:
            return []
        choices = []
        for r in self.db.execute("""SELECT * FROM memories WHERE tenant=? AND status IN
                   ('verified','reported','sandbox_verified')""", (tenant,)):
            if SENSITIVITY[r["sensitivity"]] > SENSITIVITY[clearance]:
                continue
            mem = self._memory_dict(r)
            # Do not serve a memory whose source has expired, been removed or
            # changed since its digest was recorded, irrespective of memory type.
            if not self._supports_active_memory(tenant, mem["evidence"]):
                continue
            haystack = tokens(" ".join([mem["subject"], mem["predicate"], mem["text"]]))
            overlap = len(q & haystack)
            if overlap == 0:
                continue
            score = 0.75 * overlap / len(q) + 0.15 * mem["importance"] + 0.10 * mem["confidence"]
            choices.append((score, mem))
        result = []
        used = 0
        for score, mem in sorted(choices, key=lambda x: (-x[0], x[1]["id"])):
            if used + len(mem["text"]) > max_chars:
                continue
            result.append({**mem, "retrieval_score": round(score, 5)})
            used += len(mem["text"])
            if len(result) >= limit:
                break
        return result

    def generate_hypotheses(self, tenant: str, proposer: HypothesisProposer,
                            *, consent_to_local_model: bool = False,
                            clearance: str = "public", limit: int = 32,
                            model_name: str = "local") -> list[dict[str, Any]]:
        """Opt-in LLM speculation: inspectable proposals NEVER promoted into recall.

        This call uses a user-supplied proposer and may send plaintext to the local
        model process. Only public events are shared unless clearance is raised.
        """
        if not consent_to_local_model:
            raise ValueError("Explicit consent to send events to a local model is required")
        if clearance not in SENSITIVITY or not 1 <= limit <= 128:
            raise ValueError("Invalid model event selection")
        rows = self.db.execute("""SELECT * FROM events WHERE tenant=?
            AND (expires_at IS NULL OR expires_at > ?) ORDER BY created_at DESC LIMIT ?""",
            (tenant, now_utc(), limit * 4)).fetchall()
        visible = [r for r in rows if SENSITIVITY[r["sensitivity"]] <= SENSITIVITY[clearance]][:limit]
        events = [{"id": r["id"], "subject": r["subject"], "predicate": r["predicate"],
                   "value": r["value"], "kind": r["kind"], "trust": r["trust"]}
                  for r in visible]
        if not events:
            return []
        permitted = {r["id"] for r in visible}
        candidates = proposer.propose(events)
        if not isinstance(candidates, list):
            raise ValueError("Proposer must return an array")
        run_id = str(uuid.uuid4())
        accepted = []
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for h in candidates[:3]:
                if not isinstance(h, dict):
                    continue
                claim = h.get("claim")
                rationale = h.get("rationale")
                test_plan = h.get("test_plan")
                evidence_ids = h.get("evidence_ids")
                if not all(isinstance(v, str) and 1 <= len(v) <= 1000
                           for v in (claim, rationale, test_plan)):
                    continue
                if not isinstance(evidence_ids, list) or not evidence_ids or any(
                        not isinstance(x, str) or x not in permitted for x in evidence_ids):
                    continue
                hid = str(uuid.uuid4())
                self.db.execute("""INSERT INTO hypotheses VALUES (?,?,?,?,?,?,?,?,?,?)""",
                  (hid, tenant, run_id, claim, rationale, test_plan,
                   json.dumps(evidence_ids), model_name, "untested", now_utc()))
                accepted.append({"id": hid, "claim": claim, "rationale": rationale,
                                 "test_plan": test_plan, "evidence_ids": evidence_ids,
                                 "status": "untested"})
            self._audit(tenant, run_id, "local_model_hypotheses",
                        {"received": len(candidates), "accepted": len(accepted), "shared_events": len(events)})
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return accepted

    def hypotheses(self, tenant: str) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT * FROM hypotheses WHERE tenant=? ORDER BY created_at DESC", (tenant,)).fetchall()
        return [{"id": r["id"], "claim": r["claim"], "rationale": r["rationale"],
                 "test_plan": r["test_plan"], "evidence_ids": json.loads(r["evidence_json"]),
                 "model_name": r["model_name"], "status": r["status"]} for r in rows]

    def get_audit(self, tenant: str, run_id: str | None = None) -> list[dict[str, Any]]:
        if run_id:
            rows = self.db.execute("SELECT * FROM audit WHERE tenant=? AND run_id=? ORDER BY created_at",
                                   (tenant, run_id)).fetchall()
        else:
            rows = self.db.execute("SELECT * FROM audit WHERE tenant=? ORDER BY created_at", (tenant,)).fetchall()
        return [{"action": r["action"], "details": json.loads(r["details"]),
                 "created_at": r["created_at"], "run_id": r["run_id"]} for r in rows]

    def purge_tenant(self, tenant: str) -> None:
        """Delete this tenant's rows, including audit. This is not a disk forensic wipe."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for table in ("events", "memories", "hypotheses", "audit", "dream_runs"):
                self.db.execute(f"DELETE FROM {table} WHERE tenant=?", (tenant,))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
