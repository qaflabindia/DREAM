"""E1 — Learned salience without target leakage (tests H1).

Each synthetic stream has n events and m future-query targets. Whether an event
becomes a target depends on observable features (category, failure flag,
position) through a hidden world model whose strength s is varied. s = 0 is the
null world: features carry no information about future need.

Arms (identical streams, budget k, retrieval by DreamEngine):
  recency       keep the last k events (equal importance resolves to this)
  random        uniform random importance
  learned       importance = per-feature-cell target rate estimated ONLY from
                earlier training streams of the same world (no test labels)
  bayes         importance = the true hidden target propensity (upper bound
                for any label-free method; not achievable in practice)
  oracle_label  importance = 1 for the actual targets (information leak;
                reproduces the original paper's oracle condition)

A shift condition trains on one world and tests on a world whose category
weights are permuted, to test whether learned salience fails gracefully.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

from dreamlab import DreamEngine, Event

N_CAT = 8
POS_BUCKETS = 4


def make_world(seed: int) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(0, 1) for _ in range(N_CAT)]


def propensity(world, s, cat, fail, pos, n):
    return math.exp(s * (world[cat] + 1.5 * fail + 1.0 * (pos / (n - 1))))


def make_stream(rng, world, s, n, m):
    feats = [(rng.randrange(N_CAT), int(rng.random() < 0.15), i) for i in range(n)]
    w = [propensity(world, s, c, f, i, n) for c, f, i in feats]
    # sample m distinct targets with probability proportional to propensity
    pool, weights, targets = list(range(n)), list(w), set()
    for _ in range(m):
        r, acc = rng.random() * sum(weights), 0.0
        for j, wt in enumerate(weights):
            acc += wt
            if acc >= r:
                targets.add(pool.pop(j)); weights.pop(j); break
    return feats, w, targets


def cell(c, f, i, n):
    return (c, f, min(POS_BUCKETS - 1, i * POS_BUCKETS // n))


def train(rng, world, s, n, m, n_train):
    hits, seen = {}, {}
    for _ in range(n_train):
        feats, _, targets = make_stream(rng, world, s, n, m)
        for c, f, i in feats:
            key = cell(c, f, i, n)
            seen[key] = seen.get(key, 0) + 1
            hits[key] = hits.get(key, 0) + (i in targets)
    prior, alpha = m / n, 2.0
    return lambda key: (hits.get(key, 0) + alpha * prior) / (seen.get(key, 0) + alpha)


def run_engine(feats, importance, targets, k):
    with DreamEngine(":memory:") as db:
        for (c, f, i), imp in zip(feats, importance):
            db.ingest(Event("s", f"item_{i}", f"cat{c}", "payload", f"src{i}",
                            importance=imp, trust="validated", consent=True))
        db.dream("s", max_events=len(feats), max_keys=k)
        hit = 0
        for t in targets:
            r = db.recall("s", f"item_{t} cat{feats[t][0]}", limit=1)
            hit += bool(r and r[0]["subject"] == f"item_{t}")
    return hit / len(targets)


def norm(xs):
    top = max(xs)
    return [min(1.0, max(0.0, x / top)) if top > 0 else 0.5 for x in xs]


def boot_ci(xs, rng, reps=2000):
    n = len(xs)
    means = sorted(sum(xs[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return [round(means[int(0.025 * reps)], 4), round(means[int(0.975 * reps)], 4)]


def evaluate(s, n_train, shift=False, seeds=(1, 2, 3, 4, 5), n_test=40, n=80, m=8, k=16):
    per_arm = {a: [] for a in ("recency", "random", "learned", "bayes", "oracle_label")}
    for seed in seeds:
        rng = random.Random(1000 * seed + int(10 * s) + n_train)
        world = make_world(seed)
        est = train(rng, world, s, n, m, n_train)
        test_world = world[:] if not shift else random.Random(seed + 99).sample(world, len(world))
        for _ in range(n_test):
            feats, w, targets = make_stream(rng, test_world, s, n, m)
            per_arm["recency"].append(sum(t >= n - k for t in targets) / m)
            per_arm["random"].append(run_engine(feats, [rng.random() for _ in feats], targets, k))
            per_arm["learned"].append(run_engine(feats, norm([est(cell(c, f, i, n)) for c, f, i in feats]), targets, k))
            per_arm["bayes"].append(run_engine(feats, norm(w), targets, k))
            per_arm["oracle_label"].append(run_engine(feats, [0.95 if i in targets else 0.05 for _, _, i in feats], targets, k))
    rng = random.Random(7)
    out = {a: {"mean": round(sum(v) / len(v), 4), "ci95": boot_ci(v, rng), "n_streams": len(v)} for a, v in per_arm.items()}
    diff = [l - r for l, r in zip(per_arm["learned"], per_arm["recency"])]
    out["learned_minus_recency"] = {"mean": round(sum(diff) / len(diff), 4), "ci95": boot_ci(diff, rng)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="artifacts/e1_learned_salience.json")
    args = ap.parse_args()
    results = {"design": {"n_events": 80, "targets_per_stream": 8, "memory_slots": 16,
                          "seeds": 5, "test_streams_per_seed": 40, "ci": "95% percentile bootstrap over test streams"},
               "signal_sweep_ntrain50": {}, "learning_curve_s1": {}, "shift_s1_ntrain50": None}
    for s in (0.0, 0.5, 1.0, 2.0):
        results["signal_sweep_ntrain50"][str(s)] = evaluate(s, 50)
        print("s", s, {a: v["mean"] for a, v in results["signal_sweep_ntrain50"][str(s)].items()})
    for nt in (1, 5, 20, 100):
        results["learning_curve_s1"][str(nt)] = evaluate(1.0, nt)
        print("ntrain", nt, results["learning_curve_s1"][str(nt)]["learned"])
    results["shift_s1_ntrain50"] = evaluate(1.0, 50, shift=True)
    print("shift", {a: v["mean"] for a, v in results["shift_s1_ntrain50"].items()})
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
