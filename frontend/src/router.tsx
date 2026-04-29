import { createBrowserRouter } from "react-router-dom";

import { AppShell } from "./AppShell";
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

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: "jobs/new", element: <NewJob /> },
      { path: "jobs/:jobId", element: <JobDetail /> },
      { path: "trials/:trialId", element: <TrialDetail /> },
      { path: "history", element: <History /> },
      { path: "batches", element: <Batches /> },
      { path: "batches/new", element: <BatchCreate /> },
      { path: "batches/:batchId", element: <BatchDetail /> },
      { path: "compare", element: <JobCompare /> },
      { path: "ece498", element: <ECE498 /> },
    ],
  },
]);
