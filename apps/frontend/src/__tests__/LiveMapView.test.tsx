import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { LiveMapView } from "../features/autonomy/LiveMapView";
import { getAgentCoreLiveMap, getAgentCoreLiveMapImage, type AgentCoreLiveTelemetry } from "../features/autonomy/agentCore";

vi.mock("../features/autonomy/agentCore", () => ({ getAgentCoreLiveMap: vi.fn(), getAgentCoreLiveMapImage: vi.fn() }));
afterEach(() => vi.restoreAllMocks());

it("keeps the image and route inside one aspect-preserving viewport when resized", async () => {
  const map = { schema_version: "dronedream.live-map.v1" as const, map_id: "map", map_content_sha256: "a".repeat(64),
    coordinate_frame: "gazebo-enu" as const, width_px: 2000, height_px: 1000,
    world_to_image: [4, 0, 1000, 0, -2, 500] as [number, number, number, number, number, number] };
  vi.mocked(getAgentCoreLiveMap).mockResolvedValue(map);
  vi.mocked(getAgentCoreLiveMapImage).mockResolvedValue(new Blob(["image"]));
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:registered") });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  const telemetry: AgentCoreLiveTelemetry = { schema_version: "dronedream.live-telemetry.v1", mode: "simulation",
    coordinate_frame: "gazebo-enu", map_id: map.map_id, map_content_sha256: map.map_content_sha256, updated_at_unix_ms: 1,
    route_points_m: [[0, 0, 0], [100, 0, 0]], east_m: 0, north_m: 0 };
  const view = render(<div style={{ width: 900, height: 600 }}><LiveMapView threadId="thread" telemetry={telemetry} chinese={false} /></div>);
  const svg = await screen.findByRole("img", { name: "Planned route and live position" });
  expect(svg).toHaveAttribute("viewBox", "0 0 2000 1000");
  expect(svg).toHaveAttribute("preserveAspectRatio", "xMidYMid meet");
  expect(svg.querySelector("image")).toHaveAttribute("width", "2000");
  expect(svg.querySelector("image")).toHaveAttribute("height", "1000");
  expect(svg.querySelector("polyline")).toHaveAttribute("points", "1000,500 1400,500");
  view.rerender(<div style={{ width: 400, height: 800 }}><LiveMapView threadId="thread" telemetry={telemetry} chinese={false} /></div>);
  expect(svg.querySelector("polyline")).toHaveAttribute("points", "1000,500 1400,500");
  expect(getAgentCoreLiveMapImage).toHaveBeenCalledWith("thread", map.map_content_sha256);
  view.unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:registered");
});

it("shows a map-load problem explicitly instead of using unrelated stock imagery", async () => {
  vi.mocked(getAgentCoreLiveMap).mockRejectedValue(new Error("missing registration"));
  await act(async () => render(<LiveMapView threadId="thread" telemetry={null} chinese={false} />));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Map imagery unavailable"));
  expect(screen.queryByRole("img")).toBeNull();
});
