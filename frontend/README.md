# DroneDream Frontend

React + TypeScript + Vite app for the DroneDream MVP. Renders real data
from the FastAPI backend for all required pages — Dashboard, New Job,
Job Detail, Trial Detail, History / Reports — using TanStack Query for
server-state caching and polling.

## What lives here

- `src/pages/` — route-level components:
  - `Dashboard` — summary cards + recent jobs table.
  - `NewJob` — validated form (track type, start point, altitude, wind,
    sensor noise, objective profile) that creates a job and navigates to
    its detail page.
  - `JobDetail` — polls `GET /api/v1/jobs/{id}` every 4 s while the job
    is active; renders progress, trials table, comparison chart, best
    parameters, summary text, and structured failure details.
  - `TrialDetail` — metadata, metrics, failure reason, artifacts.
  - `History` — full jobs list with links back into detail.
- `src/components/` — shared UI kit: `StatusBadge`, `MetricCard`,
  `SectionCard`, `DataTable`, `Alert`, `States` (`Loading`, `Empty`,
  `ErrorState`).
- `src/api/` — typed `apiClient` over the `/api/v1` surface; unwraps the
  standard success envelope and throws `ApiClientError` for structured
  error envelopes.
- `src/types/` — TypeScript types mirroring the backend schemas.

## Local setup

```bash
npm install
npm run dev        # http://localhost:5173
```

## Quality checks

```bash
npm run typecheck
npm run lint
npm run build
npm test            # Vitest + React Testing Library regression suite
npm run test:watch  # Vitest watcher for local TDD
```

The regression suite under [`src/__tests__/`](./src/__tests__/) covers
the `NewJob` form defaults, client-side validation (altitude range, wind
range, non-numeric inputs), failure-preserves-input behavior, and the
`apiClient`'s success/error envelope unwrap. These tests run headlessly
under JSDOM; they do not require a real browser.
