import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { MapRefinementNotice } from "../features/autonomy/MapRefinementNotice";
import { mapRefinementSnapshot } from "../features/autonomy/mapRefinement";
import { defaultAutonomyWorkspace, normalizeAutonomyWorkspace } from "../features/autonomy/workspaceStore";

const state = mapRefinementSnapshot({
  status: "map_refinement_pending", state: "awaiting-observation", thread_id: "thread-review",
  actuator_authority: false, next_action: "inspect-map-gaps", message: "The east connection needs a closer view.",
  pending_requests: [{ reason: "missing connection", focus_node_ids: ["east"], bounds_xy_m: [0, 0, 30, 30], scale: "detail" }],
  observation_records: [{ view: "overview" }], physical_calls: 1,
});

it("waits without execution controls or automatic work, and resumes only on click", () => {
  const resume = vi.fn(); const maps = vi.fn();
  render(<MapRefinementNotice state={state} chinese={false} disabled={false} onContinue={resume} onReviewMap={maps} />);
  expect(screen.getByRole("status")).toHaveAttribute("data-state", "awaiting-observation");
  expect(screen.getByText(/1 review record; 1 area needs more detail/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /simulat|execute|start/i })).not.toBeInTheDocument();
  expect(resume).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Continue planning" }));
  expect(resume).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Review map" }));
  expect(maps).toHaveBeenCalledTimes(1);
});

it("preserves waiting state when reopening a saved conversation", () => {
  const workspace = defaultAutonomyWorkspace();
  workspace.mission.mapRefinement = state;
  const restored = normalizeAutonomyWorkspace(JSON.parse(JSON.stringify(workspace)));
  expect(restored.mission.mapRefinement).toEqual(state);
  expect(restored.mission.compiledPlan).toBeNull();
  expect(restored.mission.planningError).toBeNull();
});
