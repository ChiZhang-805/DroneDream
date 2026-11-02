# DroneDream Frontend

React, TypeScript, and Vite provide three related surfaces from one source
tree: the browser application, the Tauri desktop UI, and the public product
website. TanStack Query owns server state; local drafts and desktop readiness
are kept behind dedicated adapters rather than mixed into API models.

## Application routes

- `/` — runtime-aware overview and recent experiments.
- `/jobs/new` — the gated five-step **Optimization Experiment** wizard:
  Flight Task, Parameters, Scenarios, Constraints & Budget, and Review & Run.
- `/jobs/:id` — live experiment progress, candidates, metrics, reports, replay,
  and artifacts.
- `/trials/:id` — one trial's execution evidence and artifacts.
- `/history` and `/compare` — history, reports, and experiment comparison.
- `/desktop/setup` — desktop-only prerequisite, Runtime install/repair, and
  readiness flow.
- `ECE498BH` sidebar entry — opens Professor Bin Hu's official Spring 2025
  course website in the system browser; the console does not maintain a
  separate course-content route.

The retired batch pages redirect to the overview. Batch HTTP endpoints remain
available only as an API compatibility surface; the desktop product creates and
runs one optimization experiment at a time.

Browser builds use history routing. The packaged desktop uses hash routing so
navigation continues to work from bundled files. A desktop cold start opens the
same edition landing surface as the browser console. Runtime-backed actions stay
closed until the user completes the explicit install, repair, or full re-check
flow in Settings; the retained `/desktop/setup` route owns that flow without
replacing the product workspace at every launch.

## Source layout

- `src/pages/` — route-level product pages.
- `src/features/experiment/` — wizard capabilities, draft persistence,
  parameter catalog, trial planning, and optimizer labels.
- `src/components/` — shared UI, trajectory replay/editor, Gazebo view, and the
  3D drone launch scene.
- `src/desktop/` — typed Tauri bridge, prerequisites, readiness, and access
  gating.
- `src/site/` and `site.html` — independent public download/marketing website.
- `src/i18n/` — full-page English/Simplified Chinese copy. Mixed-language
  controls are treated as defects.
- `src/api/` and `src/types/` — strict API envelope client and schema mirrors.

The 3D scene uses adaptive frame-rate and internal-resolution control. It keeps
the visual design while pausing when out of view and lowering render cost on
slower devices. Reduced-motion preferences disable nonessential animation.

## Local setup

```bash
npm ci
npm run dev          # application: http://localhost:5173
npm run site:dev     # public site (see package.json for the selected port)
```

## Quality checks

```bash
npm run typecheck
npm run lint
npm run build
npm run site:build
npm test
npm run test:watch
```

The Vitest/React Testing Library suite covers the wizard and draft contract,
desktop/runtime access, bilingual copy, API envelopes, route redirects,
trajectory editing/replay, 3D performance control, job/trial/history views, and
the public site. JSDOM tests do not replace clean-browser, clean-Windows, or
real PX4/Gazebo acceptance tests.
