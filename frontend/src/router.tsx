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
import {
  BUILD_HAS_FIELD_WORKSPACE,
  BUILD_HAS_LAB_WORKSPACE,
  BUILD_HAS_SIM_WORKSPACE,
  editionLandingPath,
} from "./edition";

function appRoutes(desktopRuntime: boolean): RouteObject[] {
  const desktopVisualQa = desktopRuntime
    && import.meta.env.VITE_DESKTOP_VISUAL_QA === "true";
  const requireDesktopReadiness = (feature: "experiment" | "job") =>
    desktopRuntime && !desktopVisualQa
      ? () => getDesktopStartupGateSession().status === "ready"
        ? null
        : redirect(`/desktop/setup?required=${feature}`)
      : undefined;
  const fallbackPath = editionLandingPath();
  const entryPath = desktopRuntime ? "/desktop/setup" : fallbackPath;

  return [
    {
      path: "/",
      element: <AppShell />,
      children: [
        {
          index: true,
          element: <Navigate to={entryPath} replace />,
        },
        ...(BUILD_HAS_SIM_WORKSPACE ? [{
          path: "sim",
          element: <Navigate to="/assistant" replace />,
        }] : []),
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
            const { AutonomyPlatform } = await import("./pages/AutonomyPlatform");
            return { Component: AutonomyPlatform };
          },
          children: [
            {
              index: true,
              lazy: async () => {
                const { AutonomyOverview } = await import("./pages/AutonomyPlatform");
                return { Component: AutonomyOverview };
              },
            },
            {
              path: "aircraft",
              lazy: async () => {
                const { AutonomyAircraft } = await import("./pages/AutonomyPlatform");
                return { Component: AutonomyAircraft };
              },
            },
            {
              path: "maps",
              lazy: async () => {
                const { AutonomyMaps } = await import("./pages/AutonomyPlatform");
                return { Component: AutonomyMaps };
              },
            },
            {
              path: "plugins",
              lazy: async () => {
                const { AutonomyPlugins } = await import("./pages/AutonomyPlugins");
                return { Component: AutonomyPlugins };
              },
            },
            {
              path: "plugins/harness",
              element: <Navigate to="/autonomy/plugins" replace />,
            },
            {
              path: "mission",
              lazy: async () => {
                const { AutonomyMissionRedirect } = await import("./pages/AutonomyPlatform");
                return { Component: AutonomyMissionRedirect };
              },
            },
            {
              path: "live",
              lazy: async () => {
                const { AutonomyLive } = await import("./pages/AutonomyPlatform");
                return { Component: AutonomyLive };
              },
            },
            {
              path: "evidence",
              element: <Navigate to="/autonomy" replace />,
            },
          ],
        },
        {
          path: "vehicle-studio",
          // Preserve old bookmarks without loading the retired modeler. Legacy
          // drafts remain readable through the qualified aircraft repository.
          element: <Navigate to="/autonomy/aircraft?source=legacy-vehicle-studio" replace />,
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
        ...(BUILD_HAS_LAB_WORKSPACE ? [{
          path: "lab",
          lazy: async () => {
            const { LabSetup } = await import("./lab/LabSetup");
            return { Component: LabSetup };
          },
        }, {
          path: "lab/hardware",
          lazy: async () => {
            const { LabHardwareWorkspace } = await import("./lab/LabHardwareWorkspace");
            return { Component: LabHardwareWorkspace };
          },
        }, {
          path: "lab/validation",
          lazy: async () => {
            const { LabValidationWorkspace } = await import("./lab/LabValidationWorkspace");
            return { Component: LabValidationWorkspace };
          },
        }] : []),
        ...(BUILD_HAS_FIELD_WORKSPACE ? [{
          path: "field",
          element: <Navigate to="/field/device" replace />,
        }, {
          path: "field/:fieldPage",
          lazy: async () => {
            const { UniversalFieldApp } = await import("./field/UniversalFieldApp");
            return { Component: UniversalFieldApp };
          },
        }] : []),
        { path: "*", loader: () => redirect(entryPath) },
      ],
    },
  ];
}

export function createAppRouter(desktopRuntime = isDesktopRuntime()) {
  const routes = appRoutes(desktopRuntime);
  // A packaged Tauri app has no HTTP server to resolve a console route after a
  // WebView reload. Hash history keeps every asset request on index.html while
  // the hosted web app retains clean browser URLs and normal deep links. The
  // Every packaged-desktop cold start enters the launcher first. The launcher
  // owns Runtime install/repair, the 0-100 readiness proof, and browser sign-in;
  // the hosted web app continues to enter the edition landing surface directly.
  if (desktopRuntime) return createHashRouter(routes);
  const pathname = window.location.pathname;
  const basename =
    pathname === "/console" || pathname.startsWith("/console/")
      ? "/console"
      : undefined;
  return createBrowserRouter(routes, basename ? { basename } : undefined);
}

export const router = createAppRouter();
