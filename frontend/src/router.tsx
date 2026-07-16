import {
  Navigate,
  createBrowserRouter,
  createHashRouter,
  redirect,
} from "react-router-dom";
import type { RouteObject } from "react-router-dom";

import { AppShell } from "./AppShell";
import { isDesktopRuntime } from "./desktop/bridge";
import { ensureOverallDesktopReadiness } from "./desktop/readiness";
import { Dashboard } from "./pages/Dashboard";
import { NewJob } from "./pages/NewJob";
import { JobDetail } from "./pages/JobDetail";
import { TrialDetail } from "./pages/TrialDetail";
import { History } from "./pages/History";
import { JobCompare } from "./pages/JobCompare";
import { ECE498 } from "./pages/ECE498";
import { DesktopSetup } from "./pages/DesktopSetup";

function appRoutes(desktopRuntime: boolean): RouteObject[] {
  const requireDesktopReadiness = (feature: "experiment" | "job") =>
    desktopRuntime
      ? async () => {
          try {
            const snapshot = await ensureOverallDesktopReadiness({ autoStart: true });
            return snapshot.ready
              ? null
              : redirect(`/dashboard?settings=runtime&required=${feature}`);
          } catch {
            return redirect(`/dashboard?settings=runtime&required=${feature}`);
          }
        }
      : undefined;
  const fallbackPath = desktopRuntime ? "/dashboard" : "/";

  return [
    {
      path: "/",
      element: <AppShell />,
      children: [
        {
          index: true,
          element: desktopRuntime
            ? <Navigate to="/desktop/setup" replace />
            : <Dashboard />,
        },
        { path: "dashboard", element: <Dashboard /> },
        {
          path: "jobs/new",
          element: <NewJob />,
          loader: requireDesktopReadiness("experiment"),
        },
        {
          path: "jobs/:jobId",
          element: <JobDetail />,
          loader: requireDesktopReadiness("job"),
        },
        {
          path: "trials/:trialId",
          element: <TrialDetail />,
          loader: requireDesktopReadiness("job"),
        },
        { path: "history", element: <History /> },
        { path: "batches/*", loader: () => redirect("/dashboard") },
        {
          path: "compare",
          element: <JobCompare />,
          loader: requireDesktopReadiness("job"),
        },
        { path: "desktop/setup", element: <DesktopSetup /> },
        { path: "ece498", element: <ECE498 /> },
        { path: "*", loader: () => redirect(fallbackPath) },
      ],
    },
  ];
}

export function createAppRouter(desktopRuntime = isDesktopRuntime()) {
  const routes = appRoutes(desktopRuntime);
  // A packaged Tauri app has no HTTP server to resolve /desktop/setup after a
  // WebView reload. Hash history keeps every asset request on index.html while
  // the hosted web app retains clean browser URLs and normal deep links.
  return desktopRuntime ? createHashRouter(routes) : createBrowserRouter(routes);
}

export const router = createAppRouter();
