# Contributing to DroneDream

Keep each change focused and preserve the repository boundaries described in
the root README.

## Before opening a pull request

1. Start from `main`; use a short-lived feature branch only when review needs it.
2. Keep credentials, generated builds, Runtime images, and user data outside
   the repository.
3. Update tests when behavior or a public contract changes.
4. Keep Chinese and English UI strings complete and separate.
5. Update the relevant guide when commands, environment variables, or
   workflows change.

## Local checks

```bash
python tools/check-repository.py
python -m ruff check server/api server/worker tools/simulators
python -m mypy server/api/app server/worker/drone_dream_worker
python -m pytest server/api/tests -q
python -m pytest shared/brand/tests release/desktop/tests runtime/engine/tests runtime/tests -q
npm --prefix apps/web run lint
npm --prefix apps/web run typecheck
npm --prefix apps/web run test
npm --prefix apps/web run build
```

Desktop and Runtime changes also require the checks in
[apps/desktop/README.md](../apps/desktop/README.md) and
[docs/development/14-runtime-release.md](../docs/development/14-runtime-release.md).

## Pull request description

Explain the user-visible or contract behavior, why the implementation changed,
and the exact checks run. Include screenshots for visible interface changes.
State any environment-dependent test that CI must complete.

Simulated results must remain identifiable as simulation results. Real flight
decisions remain with the operator.
