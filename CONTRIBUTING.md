# Contributing to DroneDream

Thanks for helping improve DroneDream. Changes should preserve its central
contract: repeatable, evidence-backed PX4/Gazebo experiments with explicit
safety and reproducibility boundaries.

## Before submitting a change

1. Create a focused branch and keep credentials and generated build output out
   of the repository.
2. Add or update tests for every behavior change.
3. Keep Chinese and English UI strings semantically equivalent and fully
   separated; do not mix languages inside one localized interface.
4. For simulator effects, provide machine-readable launcher evidence. Merely
   accepting a configuration field is not a physical implementation.
5. Update the relevant manual or architecture document when a public contract,
   workflow, environment variable, or safety boundary changes.

## Local quality gates

Run the repository-level checks before opening a pull request:

```bash
python scripts/check-repository.py
cd backend
python -m ruff check app tests alembic scripts ../worker ../scripts/simulators
python -m mypy app
python -m pytest -q
cd ..
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
npm --prefix frontend run site:build
```

Desktop and Runtime changes also require the checks documented in
[`desktop/README.md`](desktop/README.md) and
[`docs/14-runtime-release.md`](docs/14-runtime-release.md). GitHub Actions runs
the complete cross-platform gate, including Rust, Runtime contracts, container
builds, and deployment configuration checks.

## Pull request evidence

Describe:

- what user-visible or contract behavior changed;
- why the change is safe;
- the exact tests and builds executed;
- any test that could not run locally and where CI covers it; and
- screenshots for layout, localization, visualization, or 3D changes.

Do not claim that a simulated result is safe for real flight. Keep mock,
dry-run, and physically injected PX4/Gazebo results clearly labelled.
