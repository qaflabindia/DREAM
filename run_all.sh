#!/bin/sh
# Regenerate every reported artifact. Deterministic; no network.
set -e
python -m unittest discover -s tests -v > artifacts/unit_tests.txt 2>&1
python -m experiments.paired_ablation --output artifacts/paired_ablation.json
python -m experiments.evaluate --output artifacts/original_fixture.json
python -m experiments.learned_salience --output artifacts/e1_learned_salience.json
python -m experiments.counterfactual_transfer --output artifacts/e2_counterfactual_transfer.json
python -m experiments.poisoning --output artifacts/e3_poisoning.json
python -m experiments.lifecycle_invariant --output artifacts/e4_lifecycle_invariant.json
python -c "import json,platform,sqlite3;print(json.dumps({'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'package':'dreamlab-research 0.3.0','platform':platform.platform(),'network':'not required'},indent=2))" > artifacts/environment.json
python figures/make_figures.py
sha256sum dreamlab/*.py experiments/*.py tests/*.py artifacts/*.json artifacts/unit_tests.txt figures/*.py > SHA256SUMS
