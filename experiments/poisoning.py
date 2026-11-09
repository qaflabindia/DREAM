"""E3 — Memory poisoning under evidence governance (tests H3).

A clean store holds 200 true facts, each backed by 1-3 validated sources.
An attacker then injects 50 poisoned events of one type and one trust label:

  new_key      a fabricated fact about a subject the store has never seen
  contradict   a different value for an existing true fact
  sybil_new    a fabricated new fact backed by TWO forged 'validated' sources
  sybil_contra a contradiction of an existing fact with TWO forged 'validated' sources

Policies:
  naive          last write wins; no labels, no governance
  dream          DreamEngine default (one validated source suffices)
  dream_corrob2  DreamEngine(min_verified_sources=2)
  dream_dominance DreamEngine(contest_policy='dominance')
  dream_both     both options

Metrics (per attack x label x policy):
  served         poison value returned as the top recall result
  authoritative  poison returned with status 'verified'
  suppressed     (contradict only) the true value is no longer returned
Clean-store coverage reports how many true facts are served / verified
with no attack, i.e. the price of each policy.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from dreamlab import DreamEngine, Event

N_FACTS, N_POISON = 200, 50
LABELS = ("untrusted", "observed", "self_report", "validated")


def corpus(rng):
    facts = []
    for i in range(N_FACTS):
        k = rng.choices([1, 2, 3], weights=[40, 35, 25])[0]
        facts.append((f"fact{i}", f"true{i}", [f"src{i}_{j}" for j in range(k)]))
    return facts


def build(policy, facts):
    if policy == "naive":
        store = {}
        for subj, val, srcs in facts:
            for _ in srcs:
                store[subj] = val
        return store
    db = DreamEngine(":memory:", min_verified_sources=2 if policy in ("dream_corrob2", "dream_both") else 1,
                     contest_policy="dominance" if policy in ("dream_dominance", "dream_both") else "any")
    for subj, val, srcs in facts:
        for s in srcs:
            db.ingest(Event("t", subj, "value", val, s, trust="validated", consent=True))
    return db


def top(policy, store, subj):
    if policy == "naive":
        return (store[subj], "n/a") if subj in store else (None, None)
    r = store.recall("t", f"{subj} value", limit=1)
    if r and r[0]["subject"] == subj:
        return r[0]["text"].split(": ", 1)[1], r[0]["status"]
    return None, None


def attack(policy, facts, kind, label, rng):
    store = build(policy, facts)
    targets = rng.sample(range(N_FACTS), N_POISON)
    probes = []
    for n, i in enumerate(targets):
        if kind in ("contradict", "sybil_contra"):
            subj, poison = facts[i][0], f"poison{n}"
            srcs = [f"atk{n}_a", f"atk{n}_b"] if kind == "sybil_contra" else [f"atk{n}"]
        else:
            subj, poison = f"newfact{n}", f"poison{n}"
            srcs = [f"atk{n}_a", f"atk{n}_b"] if kind == "sybil_new" else [f"atk{n}"]
        for s in srcs:
            if policy == "naive":
                store[subj] = poison
            else:
                store.ingest(Event("t", subj, "value", poison, s, trust=label, consent=True))
        probes.append((subj, poison, facts[i][1]))
    if policy != "naive":
        store.dream("t", max_events=10000, max_keys=1000)
    served = auth = suppressed = 0
    for subj, poison, truth in probes:
        val, status = top(policy, store, subj)
        served += val == poison
        auth += val == poison and status == "verified"
        if kind in ("contradict", "sybil_contra"):
            suppressed += val != truth
    if policy != "naive":
        store.close()
    out = {"served": served / N_POISON, "authoritative": auth / N_POISON}
    if kind in ("contradict", "sybil_contra"):
        out["true_value_suppressed"] = suppressed / N_POISON
    return out


def coverage(policy, facts):
    store = build(policy, facts)
    if policy != "naive":
        store.dream("t", max_events=10000, max_keys=1000)
    res = [top(policy, store, s) for s, _, _ in facts]
    served = sum(v == t for (v, _), (_, t, _) in zip(res, facts)) / N_FACTS
    verified = sum(v == t and st == "verified" for (v, st), (_, t, _) in zip(res, facts)) / N_FACTS
    if policy != "naive":
        store.close()
    return {"served": served, "verified": verified}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="artifacts/e3_poisoning.json")
    args = ap.parse_args()
    rng = random.Random(2026)
    facts = corpus(rng)
    res = {"design": {"true_facts": N_FACTS, "poison_events_per_cell": N_POISON,
                      "source_mix": "1/2/3 validated sources with weights 40/35/25", "seed": 2026},
           "clean_coverage": {}, "attacks": {}}
    policies = ("naive", "dream", "dream_corrob2", "dream_dominance", "dream_both")
    for p in policies:
        res["clean_coverage"][p] = coverage(p, facts)
    for kind in ("new_key", "contradict", "sybil_new", "sybil_contra"):
        labels = ("validated",) if kind.startswith("sybil") else LABELS
        for label in labels:
            for p in policies:
                if p == "naive" and label != LABELS[0]:
                    continue  # naive ignores labels; one row suffices
                key = f"{kind}|{'any' if p == 'naive' else label}|{p}"
                res["attacks"][key] = attack(p, facts, kind, label, random.Random(f"{kind}|{label}"))
                print(key, res["attacks"][key])
    print("coverage", res["clean_coverage"])
    Path(args.output).write_text(json.dumps(res, indent=2) + "\n")


if __name__ == "__main__":
    main()
