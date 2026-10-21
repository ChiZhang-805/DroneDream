import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import * as core from "../features/autonomy/agentCore";
import { PreferredAirspaceView } from "../features/autonomy/PreferredAirspaceView";

vi.mock("three", async (original) => ({ ...await original<typeof import("three")>(),
  WebGLRenderer: class { constructor() { throw new Error("No GPU in DOM test"); } } }));

const pair = { map_asset_id: "map-one", vehicle_asset_id: "vehicle-one", map_content_sha256: "a".repeat(64), vehicle_content_sha256: "b".repeat(64) };

// 功能：
//   创建明确标为测试用的回包，模拟负高度室内层，不声称任何飞行或真实地图证据。
// 输入：
//   request：测试请求身份。
// 输出：
//   snapshot：只用于界面生命周期断言的样本。
function snapshot(request = pair) {
  return { schema_version: "dronedream.preferred-airspace.v1", coordinate_frame: "ENU", authority: "preference-only",
    airspace_sha256: "c".repeat(64), snapshot_sha256: "d".repeat(64), binding: { sources: request, radius_m: .2, height_m: .4 },
    volumes: [[0, 0, -2, 1, 1, .8, -3, 0]], obstacles: [[-1, -1, -3.2, 1, 1, -3]] };
}

describe("map-wide airspace view", () => {
  it("reports unavailable WebGL without replacing data and permits negative ENU clipping", async () => {
    const get = vi.spyOn(core, "getPreferredAirspace").mockResolvedValue(snapshot());
    render(<PreferredAirspaceView request={pair} chinese />);
    expect(await screen.findByRole("alert")).toHaveTextContent("WEBGL_UNAVAILABLE");
    const slider = screen.getByRole("slider");
    expect(slider).toHaveAttribute("min", "-2.4");
    fireEvent.click(screen.getByLabelText("高度剖切"));
    fireEvent.change(slider, { target: { value: "-2" } });
    expect(screen.getByText("-2.0 m ENU")).toBeInTheDocument();
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("ignores an old asset reply and does not reload on display changes", async () => {
    let resolveFirst!: (data: unknown) => void;
    let resolveSecond!: (data: unknown) => void;
    const get = vi.spyOn(core, "getPreferredAirspace")
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve; }));
    const view = render(<PreferredAirspaceView request={pair} chinese />);
    const next = { ...pair, map_content_sha256: "e".repeat(64) };
    view.rerender(<PreferredAirspaceView request={next} chinese />);
    await act(async () => { resolveFirst(snapshot()); });
    expect(screen.getByRole("status")).toHaveTextContent("正在读取空间数据");
    expect(screen.queryByRole("slider")).toBeNull();
    await act(async () => { resolveSecond(snapshot(next)); });
    await waitFor(() => expect(screen.getByRole("slider")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("体积中心点"));
    expect(get).toHaveBeenCalledTimes(2);
    expect(get).toHaveBeenLastCalledWith(next);
  });
});
