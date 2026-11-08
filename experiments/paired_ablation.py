"""Paired synthetic ranking ablation. Does not measure autonomous learning.

Each treatment receives the same target position, episode count, and memory
budget. Importance labels differ by intervention and are never inferred.
"""
from __future__ import annotations
import argparse
import json
import random
import tempfile
from pathlib import Path
from dreamlab import DreamEngine, Event


def evaluate(trials: int = 80, seed: int = 2026, n_events: int = 80,
             k: int = 16) -> dict:
    if not (0 < k < n_events and trials > 0):
        raise ValueError("Require 0 < budget < event count and positive trials")
    # Stratified sweep: cycle through a random permutation of all 80 possible
    # target positions before repeating. The target location is held fixed
    # across treatment modes, avoiding unrelated target-position draws.
    position_rng = random.Random(seed)
    positions = []
    while len(positions) < trials:
        block = list(range(n_events))
        position_rng.shuffle(block)
        positions.extend(block)
    positions = positions[:trials]
    hits = {"recency": 0, "oracle_importance": 0,
            "equal_importance": 0, "random_importance": 0}
    details = []
    for trial, position in enumerate(positions):
        hits["recency"] += (position >= n_events-k)
        record = {"trial": trial, "target_index": position,
                  "recency": bool(position >= n_events-k)}
        for mode in ("oracle_importance", "equal_importance", "random_importance"):
            label_rng = random.Random(seed + 7_000_003 + trial)
            with tempfile.TemporaryDirectory() as td, DreamEngine(Path(td)/"case.sqlite") as db:
                subject = f"key_{trial}"
                for i in range(n_events):
                    critical = i == position
                    if mode == "oracle_importance":
                        importance = .95 if critical else .05
                    elif mode == "equal_importance":
                        importance = .5
                    else:
                        importance = label_rng.random()
                    db.ingest(Event("synthetic", subject if critical else f"noise_{i}",
                                    "operation", "critical check" if critical else "ordinary check",
                                    f"generated-{trial}-{i}", importance=importance,
                                    trust="validated", consent=True))
                db.dream("synthetic", max_events=n_events, max_keys=k)
                recalled = db.recall("synthetic", f"{subject} operation", limit=1)
                hit = bool(recalled and recalled[0]["subject"] == subject)
                hits[mode] += hit
                record[mode] = hit
        details.append(record)
    return {"name":"paired_synthetic_ranking_ablation", "seed":seed,
        "n_trials":trials, "n_events":n_events, "memory_slots":k,
        "estimand":"target recall on synthetic labelled items, not future-task uplift",
        "rates":{key:{"hits":int(val),"trials":trials,"rate":round(val/trials,4)}
                 for key,val in hits.items()},
        "interpretation":"Oracle-importance labels encode the target; this is an information advantage, not learned salience.",
        "falsification":"If importance is uninformative, selection offers no reliable benefit over recency.",
        "raw_trials":details}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials",type=int,default=80)
    parser.add_argument("--seed",type=int,default=2026)
    parser.add_argument("--output",default="artifacts/paired_ablation.json")
    args=parser.parse_args()
    result=evaluate(args.trials,args.seed)
    path=Path(args.output)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result["rates"],indent=2))

if __name__=='__main__': main()
