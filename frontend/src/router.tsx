import {
  Navigate,
  createBrowserRouter,
  createHashRouter,
  redirect,
} from "react-router-dom";
import type { RouteObject } from "react-router-dom";

import { AppShell } from "./AppShell";
import { isDesktopRuntime } from "./desktop/bridge";
import { getDesktopStartupGateSession } from "./desktop/startupGate";

function appRoutes(desktopRuntime: boolean): RouteObject[] {
  const requireDesktopReadiness = (feature: "experiment" | "job") =>
    desktopRuntime
      ? () => getDesktopStartupGateSession().status === "ready"
        ? null
        : redirect(`/dashboard?settings=runtime&required=${feature}`)
      : undefined;
  const fallbackPath = "/sim";

  return [
    {
      path: "/",
      element: <AppShell />,
      children: [
        {
          index: true,
          element: desktopRuntime
            ? <Navigate to="/desktop/setup" replace />
            : <Navigate to="/sim" replace />,
        },
        {
          path: "sim",
          lazy: async () => {
            const { SimOverview } = await import("./pages/SimOverview");
            return { Component: SimOverview };
          },
        },
        {
          path: "assistant",
          lazy: async () => {
            const { ExperimentAssistant } = await import("./pages/ExperimentAssistant");
            return { Component: ExperimentAssistant };
          },
          loader: requireDesktopReadiness("experiment"),
        },
        {
          path: "dashboard",
          lazy: async () => {
            const { Dashboard } = await import("./pages/Dashboard");
            return { Component: Dashboard };
          },
        },
        {
          path: "jobs/new",
          lazy: async () => {
            const { NewJobRoute } = await import("./pages/NewJobRoute");
            return { Component: NewJobRoute };
          },
          loader: requireDesktopReadiness("experiment"),
        },
        {
          path: "jobs/:jobId",
          lazy: async () => {
            const { JobDetail } = await import("./pages/JobDetail");
            return { Component: JobDetail };
          },
          loader: requireDesktopReadiness("job"),
        },
        {
          path: "trials/:trialId",
          lazy: async () => {
            const { TrialDetail } = await import("./pages/TrialDetail");
            return { Component: TrialDetail };
          },
          loader: requireDesktopReadiness("job"),
        },
        {
          path: "history",
          lazy: async () => {
            const { History } = await import("./pages/History");
            return { Component: History };
          },
        },
        {
          path: "scenarios",
          lazy: async () => {
            const { FixedScenarios } = await import("./pages/FixedScenarios");
            return { Component: FixedScenarios };
          },
        },
        {
          path: "autonomy",
          lazy: async () => {
            const { AutonomyGateway } = await import("./pages/AutonomyGateway");
            return { Component: AutonomyGateway };
          },
        },
        {
          path: "admin",
          lazy: async () => {
            const { AdminPage } = await import("./pages/AdminPage");
            return { Component: AdminPage };
          },
          loader: desktopRuntime ? () => redirect("/assistant") : undefined,
        },
        { path: "batches/*", loader: () => redirect("/dashboard") },
        {
          path: "compare",
          lazy: async () => {
            const { JobCompare } = await import("./pages/JobCompare");
            return { Component: JobCompare };
          },
          loader: requireDesktopReadiness("job"),
        },
        {
          path: "desktop/setup",
          lazy: async () => {
            const { DesktopSetup } = await import("./pages/DesktopSetup");
            return { Component: DesktopSetup };
          },
        },
        {
          path: "lab/*",
          loader: () => redirect("/sim?blocked=lab"),
        },
        {
          path: "field/*",
          loader: () => redirect("/sim?blocked=field"),
        },
        {
          path: "hitl/*",
          loader: () => redirect("/sim?blocked=hitl"),
        },
        {
          path: "hardware/*",
          loader: () => redirect("/sim?blocked=hardware"),
        },
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
  if (desktopRuntime) return createHashRouter(routes);
  const pathname = window.location.pathname;
  const basename =
    pathname === "/console" || pathname.startsWith("/console/")
      ? "/console"
      : undefined;
  return createBrowserRouter(routes, basename ? { basename } : undefined);
}

export const router = createAppRouter();
