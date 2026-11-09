"""E2 — Does tested counterfactual promotion improve later, unseen tasks? (H2)

Six registered task families (dreamlab.families). In each, an agent starts with
a naive default action and experiences a few training episodes. After each
episode it observes a reference answer that is wrong with probability eps
(noisy feedback). Arms differ only in how they turn experience into a rule:

  base          never changes the default action
  retrieval     stores outcomes; keeps the action with the best observed
                success rate, trying an untried action after each failure
  reflection    after an observed failure, adopts one alternative that would
                have matched the reference on that single episode (untested)
  dream         after an observed failure, quarantines every alternative that
                matches the episode, tests them and the current action on F
                independently generated fixtures scored by a separate test
                authority, and promotes only a clear winner
  retrieval+ / reflection+
                as above but given extra real episodes equal to dream's
                evaluator calls (budget-matched)
  oracle        the environment's true convention (upper bound)

Test accuracy is measured on 300 unseen instances per family with exact ground
truth. The test authority is exact, noisy (labels wrong with probability 0.2),
or misspecified (encodes a wrong convention) to test when promotion harms.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from dreamlab.families import FAMILIES, same

F_FIXTURES = 20
N_TEST = 300


def noisy_reference(fam, x, eps, rng):
    ref = fam.reference(x)
    if rng.random() < eps:
        wrong = [fam.run(a, x) for a in fam.actions if not same(fam.run(a, x), ref)]
        if wrong:
            return rng.choice(wrong)
    return ref


def authority_label(fam, x, mode, rng):
    if mode == "misspecified":
        wrong_truth = next(a for a in fam.actions if a != fam.truth)
        return fam.run(wrong_truth, x)
    return noisy_reference(fam, x, 0.2 if mode == "noisy" else 0.0, rng)


class Retrieval:
    def __init__(self, fam, rng):
        self.fam, self.rng = fam, rng
        self.stats = {a: [0, 0] for a in fam.actions}
        self.current, self.cost = fam.default, 0

    def best(self):
        tried = [a for a, (s, n) in self.stats.items() if n]
        if not tried:
            return self.fam.default
        return max(tried, key=lambda a: (self.stats[a][0] / self.stats[a][1], self.stats[a][1]))

    def episode(self, x, ref):
        ok = same(self.fam.run(self.current, x), ref)
        st = self.stats[self.current]; st[0] += ok; st[1] += 1
        if not ok:
            untried = [a for a, (_, n) in self.stats.items() if n == 0]
            self.current = self.rng.choice(untried) if untried else self.best()
        else:
            self.current = self.best()

    def policy(self):
        return self.best()


class Reflection:
    def __init__(self, fam, rng):
        self.fam, self.rng, self.current, self.cost = fam, rng, fam.default, 0

    def episode(self, x, ref):
        if same(self.fam.run(self.current, x), ref):
            return
        fixes = [a for a in self.fam.actions if a != self.current and same(self.fam.run(a, x), ref)]
        if fixes:
            self.current = self.rng.choice(fixes)

    def policy(self):
        return self.current


class Dream:
    def __init__(self, fam, rng, authority):
        self.fam, self.rng, self.authority = fam, rng, authority
        self.current, self.cost, self.promotions = fam.default, 0, 0

    def episode(self, x, ref):
        if same(self.fam.run(self.current, x), ref):
            return
        hyps = [a for a in self.fam.actions if a != self.current and same(self.fam.run(a, x), ref)]
        if not hyps:
            return
        fixtures = [self.fam.generate(self.rng) for _ in range(F_FIXTURES)]
        labels = [authority_label(self.fam, f, self.authority, self.rng) for f in fixtures]
        score = {a: sum(same(self.fam.run(a, f), l) for f, l in zip(fixtures, labels))
                 for a in [self.current, *hyps]}
        self.cost += F_FIXTURES * (len(hyps) + 1)
        best = max(hyps, key=lambda a: score[a])
        if score[best] - score[self.current] >= max(2, F_FIXTURES // 10):
            self.current, self.promotions = best, self.promotions + 1

    def policy(self):
        return self.current


def train(agent, fam, n, eps, rng):
    for _ in range(n):
        x = fam.generate(rng)
        agent.episode(x, noisy_reference(fam, x, eps, rng))
    return agent


def test_acc(fam, action, xs):
    return sum(fam.correct(action, x) for x in xs) / len(xs)


def boot(xs, rng, reps=2000):
    n = len(xs)
    m = sorted(sum(xs[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return [round(m[int(.025 * reps)], 4), round(m[int(.975 * reps)], 4)]


def condition(n_train, eps, authority, seeds=30):
    rows = []
    for fname, fam in FAMILIES.items():
        for seed in range(seeds):
            rng = random.Random(f"{fname}|{seed}|{n_train}|{eps}|{authority}")
            xs = [fam.generate(rng) for _ in range(N_TEST)]
            d = train(Dream(fam, rng, authority), fam, n_train, eps, rng)
            extra = n_train + min(d.cost, 400)
            arms = {
                "base": fam.default,
                "retrieval": train(Retrieval(fam, rng), fam, n_train, eps, rng).policy(),
                "reflection": train(Reflection(fam, rng), fam, n_train, eps, rng).policy(),
                "dream": d.policy(),
                "retrieval+": train(Retrieval(fam, rng), fam, extra, eps, rng).policy(),
                "reflection+": train(Reflection(fam, rng), fam, extra, eps, rng).policy(),
                "oracle": fam.truth,
            }
            rows.append({"family": fname, "seed": seed, "dream_cost": d.cost,
                         **{a: test_acc(fam, act, xs) for a, act in arms.items()}})
    rng = random.Random(11)
    arms = ["base", "retrieval", "reflection", "dream", "retrieval+", "reflection+", "oracle"]
    out = {a: {"mean": round(sum(r[a] for r in rows) / len(rows), 4),
               "ci95": boot([r[a] for r in rows], rng),
               "regression_rate": round(sum(r[a] < r["base"] - 0.02 for r in rows) / len(rows), 4)}
           for a in arms}
    for a in ("retrieval", "reflection", "retrieval+", "reflection+"):
        diff = [r["dream"] - r[a] for r in rows]
        out[f"dream_minus_{a}"] = {"mean": round(sum(diff) / len(diff), 4), "ci95": boot(diff, rng)}
    out["dream_evaluator_calls_mean"] = round(sum(r["dream_cost"] for r in rows) / len(rows), 1)
    out["per_family_mean"] = {f: {a: round(sum(r[a] for r in rows if r["family"] == f) / seeds, 3)
                                  for a in arms} for f in FAMILIES}
    out["units"] = len(rows)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="artifacts/e2_counterfactual_transfer.json")
    args = ap.parse_args()
    res = {"design": {"families": list(FAMILIES), "seeds_per_family": 30, "fixtures_per_test": F_FIXTURES,
                      "test_instances": N_TEST, "ci": "95% percentile bootstrap over family x seed units"},
           "exact_authority": {}, "authority_stress": {}}
    for n_train in (1, 3, 10):
        for eps in (0.0, 0.1, 0.3):
            key = f"ntrain={n_train},eps={eps}"
            res["exact_authority"][key] = c = condition(n_train, eps, "exact")
            print(key, {a: c[a]["mean"] for a in ("base", "retrieval", "reflection", "dream", "retrieval+", "reflection+")},
                  "cost", c["dream_evaluator_calls_mean"])
    for auth in ("noisy", "misspecified"):
        res["authority_stress"][auth] = c = condition(10, 0.1, auth)
        print(auth, {a: (c[a]["mean"], c[a]["regression_rate"]) for a in ("base", "retrieval", "reflection", "dream")})
    Path(args.output).write_text(json.dumps(res, indent=2) + "\n")


if __name__ == "__main__":
    main()
