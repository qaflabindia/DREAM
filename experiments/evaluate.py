"""Seeded synthetic memory-budget evaluation: intentionally limited toy stress test.
Run: python experiments/evaluate.py --output results.json
"""
from __future__ import annotations
import argparse
import json
import random
import tempfile
from pathlib import Path

from dreamlab import DreamEngine, Event
from dreamlab.scenarios import evaluate_counterfactual


def evaluate(trials: int = 50, seed: int = 2026, event_count: int = 80, budget: int = 16) -> dict:
    rng = random.Random(seed)
    baseline_hits = 0
    dream_hits = 0
    for trial in range(trials):
        with tempfile.TemporaryDirectory() as td, DreamEngine(Path(td) / "test.db") as engine:
            target_at = rng.randrange(event_count)
            subject = f"critical_safeguard_{trial}"
            observed = []
            for i in range(event_count):
                if i == target_at:
                    ev = Event("benchmark", subject, "method", f"preflight validation for task {trial}",
                               f"source-{trial}-critical", importance=0.95, trust="validated", consent=True)
                else:
                    ev = Event("benchmark", f"noise_{i}", "method", "routine check",
                               f"source-{trial}-{i}", importance=0.05, trust="validated", consent=True)
                engine.ingest(ev)
                observed.append(ev)
            # Naive FIFO-recent memory stores the last `budget` distinct event slots.
            baseline_hits += any(e.subject == subject for e in observed[-budget:])
            # DREAM uses identical knowledge budget, but selects by event impact.
            engine.dream("benchmark", max_events=event_count, max_keys=budget)
            recalled = engine.recall("benchmark", f"{subject} method", limit=1)
            dream_hits += bool(recalled and recalled[0]["subject"] == subject)
    cf = evaluate_counterfactual("decimal_sum", "binary_float")
    return {
        "experiment": "Seeded synthetic salience-targeted lookup, NOT a real-world agent benchmark",
        "seed": seed, "trials": trials, "events_per_trial": event_count,
        "memory_slot_budget": budget,
        "baseline": "FIFO recency, last K events",
        "treatment": "priority-based offline selection plus lexical recall",
        "baseline_successes": baseline_hits, "dream_successes": dream_hits,
        "baseline_success_rate": round(baseline_hits / trials, 4),
        "dream_success_rate": round(dream_hits / trials, 4),
        "counterfactual_fixture": cf,
        "limitations": [
            "Critical items are assigned higher importance by construction.",
            "One target query per trial; no natural-language ambiguity.",
            "No language model, user study, independent external validation or statistical generalization.",
            "Fixture tests establish correctness only on the defined decimal_sum cases.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="results.json")
    parser.add_argument("--trials", type=int, default=50)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    data = evaluate(args.trials, args.seed)
    Path(args.output).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
