# DREAM — Evidence-Governed Counterfactual Consolidation

**Author:** Lakshminarasimhan Santhanam

DREAM is a local Python research prototype for retaining provenance-linked
experience, consolidating evidence, detecting contradictions, testing a bounded
class of counterfactual scenarios, and retrieving eligible memories.

It uses SQLite and the Python standard library. No hosted model is required.
An optional localhost-only model adapter proposes **untested hypotheses**;
its outputs are never automatically promoted as verified memories.

## Run locally

Requirements: Python 3.10 or newer.

```bash
python -m unittest discover -s tests -v
python -m experiments.paired_ablation --output artifacts/paired_ablation.json
python -m experiments.evaluate --output artifacts/original_fixture.json
python -m dreamlab.cli --db ./example.sqlite demo
```

For command-line help:

```bash
python -m dreamlab.cli --help
```

## Project structure

- `dreamlab/` — evidence store, consolidation engine, retrieval, optional model adapter, CLI
- `experiments/` — deterministic synthetic evaluations and paired ablation
- `tests/` — unit tests and adversarial governance cases
- `artifacts/` — reproducibility metadata, synthetic records, and test log
- `figures/` — architecture figure source

## Scope of evidence

The paired retention experiment uses synthetic events with deliberately
assigned importance signals. The oracle condition is not evidence that
importance is learned. The counterfactual simulator handles only predefined
safe scenarios. The present implementation does not establish autonomous
learning, production security, or generalizable downstream performance.

## Security boundaries

This is a research prototype, not a secure multi-tenant service. The SQLite
store is unencrypted. Tenant identifiers and clearance values are not
authenticated. SHA-256 integrity checks do not provide cryptographic
authenticity against an attacker who can rewrite the database.

Do not ingest secrets, personal records, or confidential information. The
optional local model can receive event content only by an explicit opt-in.
Review and isolate any experiments before using outside supplied fixtures.

## Research status

Source code and reproducibility materials are provided for technical
inspection. A publication-level claim of improved downstream agent
performance requires independent held-out evaluations and author approval.
