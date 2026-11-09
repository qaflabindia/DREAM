"""Write artifacts/Reproducibility_Summary.json from the other artifacts."""
import json
import re
from pathlib import Path

A = Path("artifacts")
load = lambda n: json.loads((A / n).read_text())


def main():
    tests = (A / "unit_tests.txt").read_text()
    ran = int(re.search(r"Ran (\d+) tests", tests).group(1))
    failed = sum(int(n) for n in re.findall(r"(?:failures|errors)=(\d+)", tests))
    pa, e1, e2, e3, e4 = (load("paired_ablation.json"), load("e1_learned_salience.json"),
                          load("e2_counterfactual_transfer.json"), load("e3_poisoning.json"),
                          load("e4_lifecycle_invariant.json"))
    pick = lambda c, arms: {a: {"mean": c[a]["mean"], "ci95": c[a]["ci95"]} for a in arms}
    summary = {
        "document": "Research Gate Document",
        "author": "Lakshminarasimhan Santhanam",
        "environment": load("environment.json"),
        "unit_tests": {"ran": ran, "failed": failed},
        "calibration_fixture": {
            "rates": pa["rates"],
            "note": "equal_importance is identical to recency by construction (ties resolve newest-first)",
        },
        "e1_learned_salience": {
            "signal_sweep": {s: pick(v, ["recency", "random", "learned", "bayes"]) | {
                "learned_minus_recency": v["learned_minus_recency"]} for s, v in e1["signal_sweep_ntrain50"].items()},
            "distribution_shift": pick(e1["shift_s1_ntrain50"], ["recency", "learned", "bayes"]),
        },
        "e2_counterfactual_transfer": {
            "exact_authority": {k: pick(c, ["base", "retrieval+", "reflection+", "dream"]) | {
                "dream_minus_retrieval+": c["dream_minus_retrieval+"],
                "dream_minus_reflection+": c["dream_minus_reflection+"],
                "dream_evaluator_calls_mean": c["dream_evaluator_calls_mean"]}
                for k, c in e2["exact_authority"].items()},
            "authority_stress": {k: pick(c, ["base", "retrieval+", "reflection+", "dream"]) | {
                "dream_regression_rate": c["dream"]["regression_rate"]} for k, c in e2["authority_stress"].items()},
        },
        "e3_poisoning": {"clean_coverage": e3["clean_coverage"], "attacks": e3["attacks"]},
        "e4_lifecycle_invariant": e4,
        "scope": "Controlled simulations and software tests only; no language-model agent, external benchmark or peer review.",
    }
    (A / "Reproducibility_Summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
