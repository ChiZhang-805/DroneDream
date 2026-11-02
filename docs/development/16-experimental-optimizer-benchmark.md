# Experimental optimizer benchmark

DroneDream includes a small deterministic benchmark for the seven experimental
optimizer strategies. It is a numerical regression and integration aid, not a
claim about real PX4/Gazebo or flight performance.

Run it from the repository root:

```powershell
backend\.venv\Scripts\python.exe backend\scripts\benchmark_experimental_optimizers.py
```

To write machine-readable results:

```powershell
backend\.venv\Scripts\python.exe backend\scripts\benchmark_experimental_optimizers.py `
  --generations 3 --batch-size 3 --seed 805 `
  --output artifacts\optimizer-synthetic-benchmark.json
```

Every strategy receives the same parameter domain, mixed feasible and failed
initial observations, two minimization objectives, direction-aware non-negative
constraint-violation margins,
generation count, batch size, and deterministic seed. The report compares:

- number of proposed evaluations;
- full-fidelity, feasible, and failed evaluation counts;
- best feasible loss among evaluations that actually ran at requested and
  effective full fidelity;
- a separately labelled hidden-oracle diagnostic for every queried point;
- improvement over the common initial design;
- total effective-fidelity evaluation cost;
- best parameter vector and a digest of the complete result.

Only the executed full-fidelity value participates in the formal ranking. The
`oracle_best_queried_loss` field is useful for numerical diagnostics, but it is
not treated as a verified result and never substitutes for an evaluation the
optimizer did not run.

Failed observations intentionally have no fabricated scalar loss. Their
direction-aware constraint-violation margins, infeasible label, and failure
rate remain in the shared history, so all seven policies receive the same
crash/failure feedback.

Use this benchmark to catch non-determinism, invalid proposals, failure-feedback
regressions, or a strategy that stops producing candidates. Real algorithm
selection must still be based on repeated PX4/Gazebo campaigns with identical
tracks, scenario suites, seeds, trial budgets, acceptance rules, and holdout
cases.
