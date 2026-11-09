"""E4 — Randomized check of the read-time evidence invariant (tests H4).

Random traces interleave ingestion (facts and test-backed procedures, with and
without expiry), clock advances, dream cycles, direct row tampering, direct row
deletion and recalls. After every recall, an independent checker re-derives
whether each served memory's supporting events exist, are tenant-local,
unexpired at the current (simulated) time and match their stored digest.

To show the checker can detect faults, the same traces are replayed against a
mutant engine whose read-time revalidation is disabled.
"""
from __future__ import annotations

import argparse
import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import dreamlab.engine as eng
from dreamlab import DreamEngine, Event
from dreamlab.engine import IntegrityError, event_digest

T0 = datetime(2030, 1, 1, tzinfo=timezone.utc)


def check(db, tenant, served, now):
    bad = 0
    for mem in served:
        for eid in mem["evidence"]:
            r = db.db.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
            if (r is None or r["tenant"] != tenant
                    or (r["expires_at"] and r["expires_at"] <= now)
                    or event_digest(dict(r)) != r["digest"]):
                bad += 1
                break
    return bad


def trace(seed, mutant=False, steps=60):
    rng = random.Random(seed)
    clock = {"t": T0}
    now = lambda: clock["t"].isoformat()
    stats = {"recalls": 0, "served": 0, "violations": 0, "fail_closed_recalls": 0,
             "fail_closed_dreams": 0, "tampers": 0, "deletions": 0}
    id_rng = random.Random(f"ids-{seed}")
    patches = [patch.object(eng, "now_utc", now),
               patch.object(eng.uuid, "uuid4", lambda: uuid.UUID(int=id_rng.getrandbits(128), version=4))]
    if mutant:
        patches.append(patch.object(DreamEngine, "_supports_active_memory", lambda self, t, e: bool(e)))
    for p in patches:
        p.start()
    try:
        with DreamEngine(":memory:") as db:
            keys = [f"k{i}" for i in range(8)]
            for _ in range(steps):
                op = rng.choices(["ingest", "proc", "tick", "dream", "tamper", "delete", "recall"],
                                 weights=[30, 6, 15, 12, 3, 3, 31])[0]
                if op in ("ingest", "proc"):
                    exp = (clock["t"] + timedelta(minutes=rng.randrange(1, 60))).isoformat() if rng.random() < 0.5 else None
                    if op == "ingest":
                        db.ingest(Event("t", rng.choice(keys), "state", rng.choice(["a", "b"]), f"s{rng.randrange(99)}",
                                        trust=rng.choice(["validated", "validated", "observed", "self_report", "untrusted"]),
                                        consent=True, expires_at=exp))
                    else:
                        db.ingest(Event("t", "decimal_sum", "attempt", "failed", f"run{rng.randrange(99)}",
                                        kind="outcome", trust="validated", consent=True, expires_at=exp,
                                        payload={"scenario": "decimal_sum", "action": "binary_float"}))
                elif op == "tick":
                    clock["t"] += timedelta(minutes=rng.randrange(1, 30))
                elif op == "dream":
                    try:
                        db.dream("t")
                    except IntegrityError:
                        stats["fail_closed_dreams"] += 1
                elif op in ("tamper", "delete"):
                    ids = [r["id"] for r in db.db.execute("SELECT id FROM events ORDER BY rowid")]
                    row = {"id": rng.choice(ids)} if ids else None
                    if row:
                        if op == "tamper":
                            db.db.execute("UPDATE events SET value=value||'x' WHERE id=?", (row["id"],)); stats["tampers"] += 1
                        else:
                            db.db.execute("DELETE FROM events WHERE id=?", (row["id"],)); stats["deletions"] += 1
                else:
                    for q in [f"{k} state" for k in keys] + ["decimal_sum action_policy"]:
                        stats["recalls"] += 1
                        try:
                            served = db.recall("t", q, limit=5)
                        except IntegrityError:
                            stats["fail_closed_recalls"] += 1
                            continue
                        stats["served"] += len(served)
                        stats["violations"] += check(db, "t", served, now())
    finally:
        for p in reversed(patches):
            p.stop()
    return stats


def total(runs):
    return {k: sum(r[k] for r in runs) for k in runs[0]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="artifacts/e4_lifecycle_invariant.json")
    ap.add_argument("--traces", type=int, default=500)
    args = ap.parse_args()
    real = total([trace(s) for s in range(args.traces)])
    mutant = total([trace(s, mutant=True) for s in range(args.traces)])
    res = {"traces": args.traces, "steps_per_trace": 60, "engine": real, "mutant_no_read_revalidation": mutant}
    print(json.dumps(res, indent=1))
    Path(args.output).write_text(json.dumps(res, indent=2) + "\n")


if __name__ == "__main__":
    main()
