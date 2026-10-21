# Contributing to DroneDream

Keep each change focused and preserve the repository boundaries described in
the root README.

## Before opening a pull request

1. Start from the long-lived branch that owns the change.
2. Keep credentials, generated builds, Runtime images, and user data outside
   the repository.
3. Update tests when behavior or a public contract changes.
4. Keep Chinese and English UI strings complete and separate.
5. Update the relevant guide when commands, environment variables, or
   workflows change.

## Local checks

```bash
python tools/check-repository.py
python -m ruff check services/backend services/worker tools/simulators
python -m mypy services/backend/app services/worker/drone_dream_worker
python -m pytest services/backend/tests -q
python -m pytest shared/brand/tests release/distribution/tests platform/engine-pack/tests platform/runtime/tests -q
npm --prefix apps/frontend run lint
npm --prefix apps/frontend run typecheck
npm --prefix apps/frontend run test
npm --prefix apps/frontend run build
```

Desktop and Runtime changes also require the checks in
[apps/desktop/README.md](../apps/desktop/README.md) and
[docs/guides/14-runtime-release.md](../docs/guides/14-runtime-release.md).

## Pull request description

Explain the user-visible or contract behavior, why the implementation changed,
and the exact checks run. Include screenshots for visible interface changes.
State any environment-dependent test that CI must complete.

Simulated results must remain identifiable as simulation results. Real flight
decisions remain with the operator.
