import {
  Navigate,
  createBrowserRouter,
  createHashRouter,
  redirect,
} from "react-router-dom";
import type { RouteObject } from "react-router-dom";

import { AppShell } from "./AppShell";
import { isDesktopRuntime } from "./desktop/bridge";
import { probeOverallDesktopReadiness } from "./desktop/readiness";
import { Dashboard } from "./pages/Dashboard";
import { NewJob } from "./pages/NewJob";
import { JobDetail } from "./pages/JobDetail";
import { TrialDetail } from "./pages/TrialDetail";
import { History } from "./pages/History";
import { JobCompare } from "./pages/JobCompare";
import { BatchCreate } from "./pages/BatchCreate";
import { BatchDetail } from "./pages/BatchDetail";
import { Batches } from "./pages/Batches";
import { ECE498 } from "./pages/ECE498";
import { DesktopSetup } from "./pages/DesktopSetup";

function appRoutes(desktopRuntime: boolean): RouteObject[] {
  const requireDesktopReadiness = desktopRuntime
    ? async () => {
        try {
          const snapshot = await probeOverallDesktopReadiness();
          return snapshot.ready ? null : redirect("/desktop/setup");
        } catch {
          return redirect("/desktop/setup");
        }
      }
    : undefined;
  const fallbackPath = desktopRuntime ? "/desktop/setup" : "/";

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
        { path: "dashboard", element: <Dashboard />, loader: requireDesktopReadiness },
        { path: "jobs/new", element: <NewJob />, loader: requireDesktopReadiness },
        { path: "jobs/:jobId", element: <JobDetail />, loader: requireDesktopReadiness },
        { path: "trials/:trialId", element: <TrialDetail />, loader: requireDesktopReadiness },
        { path: "history", element: <History />, loader: requireDesktopReadiness },
        { path: "batches", element: <Batches />, loader: requireDesktopReadiness },
        { path: "batches/new", element: <BatchCreate />, loader: requireDesktopReadiness },
        { path: "batches/:batchId", element: <BatchDetail />, loader: requireDesktopReadiness },
        { path: "compare", element: <JobCompare />, loader: requireDesktopReadiness },
        { path: "desktop/setup", element: <DesktopSetup /> },
        { path: "ece498", element: <ECE498 />, loader: requireDesktopReadiness },
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
