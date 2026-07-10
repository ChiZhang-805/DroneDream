import {
  Navigate,
  createBrowserRouter,
  createHashRouter,
} from "react-router-dom";
import type { RouteObject } from "react-router-dom";

import { AppShell } from "./AppShell";
import { isDesktopRuntime } from "./desktop/bridge";
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
        { path: "jobs/new", element: <NewJob /> },
        { path: "jobs/:jobId", element: <JobDetail /> },
        { path: "trials/:trialId", element: <TrialDetail /> },
        { path: "history", element: <History /> },
        { path: "batches", element: <Batches /> },
        { path: "batches/new", element: <BatchCreate /> },
        { path: "batches/:batchId", element: <BatchDetail /> },
        { path: "compare", element: <JobCompare /> },
        { path: "desktop/setup", element: <DesktopSetup /> },
        { path: "ece498", element: <ECE498 /> },
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
