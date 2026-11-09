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
sh run_all.sh            # tests + every experiment + figures + SHA256SUMS (about 3 minutes)
python -m dreamlab.cli --db ./example.sqlite demo
```

Individual experiments:

| Runner | Tests | Output |
|---|---|---|
| `experiments.paired_ablation` | calibration fixture (oracle leak) | `artifacts/paired_ablation.json` |
| `experiments.learned_salience` | H1 learned salience, null and shift conditions | `artifacts/e1_learned_salience.json` |
| `experiments.counterfactual_transfer` | H2 transfer vs budget-matched baselines, authority stress | `artifacts/e2_counterfactual_transfer.json` |
| `experiments.poisoning` | H3 poisoning under default, corroboration and dominance policies | `artifacts/e3_poisoning.json` |
| `experiments.lifecycle_invariant` | H4 randomized read-time invariant check with mutant control | `artifacts/e4_lifecycle_invariant.json` |

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

## Promotion policies

`DreamEngine(path, min_verified_sources=1, contest_policy="any")` reproduces the
original behaviour. `min_verified_sources=2` requires two distinct validated
sources for `verified`; `contest_policy="dominance"` keeps a strictly stronger
value servable instead of withholding the key. Source identifiers are not
authenticated, so neither option is proof against forged evidence (see E3).

## Scope of evidence

All results are controlled simulations with stated assumptions; none involves
a language-model agent or an external benchmark. In brief: learned salience
beats recency when features carry signal but not in a null world or under
shift (E1); tested promotion beats budget-matched baselines only under noisy
feedback, and harms when the test authority is misspecified (E2); governance
blocks low-trust poison but not forged validated labels (E3); read-time
revalidation showed zero violations in randomized traces (E4). The present
implementation does not establish autonomous learning, production security, or
generalizable downstream performance.

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
